from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Iterable

import websockets
from websockets.exceptions import WebSocketException

from .config import RuntimeConfig
from .pipeline import Signal, StrategyProducer
from .universe import UniverseManager

BINANCE_FUTURES_STREAM = "wss://fstream.binance.com/stream?streams={streams}"
BINANCE_SPOT_STREAM = "wss://stream.binance.com:9443/stream?streams={streams}"


def _now() -> float:
    return time.time()


class BaseStreamProducer(StrategyProducer):
    stream_suffix: str
    endpoint: str

    def __init__(self, name: str, manager: UniverseManager) -> None:
        super().__init__(name)
        self.manager = manager
        self._log = logging.getLogger(f"engine.runtime.{name}")
        self.stream_suffix = "@markPrice@1s"
        self.endpoint = BINANCE_FUTURES_STREAM
        self._active_symbols: tuple[str, ...] = ()
        self._suppressed_errors = (
            ConnectionError,
            OSError,
            RuntimeError,
            asyncio.TimeoutError,
            WebSocketException,
        )

    async def run(self, bus: asyncio.Queue[tuple[Signal, float]], config: RuntimeConfig) -> None:
        self._running = True
        version, symbols = await self.manager.current(self.name)
        while self._running:
            if not symbols:
                version = await self.manager.wait_for_update(self.name, version)
                version, symbols = await self.manager.current(self.name)
                continue
            self._log.info("[%s] universe size=%d", self.name, len(symbols))
            new_version = await self._stream_until_update(symbols, version, bus, config)
            version, symbols = await self.manager.current(self.name)
            if new_version is not None:
                version = new_version

    async def _stream_until_update(
        self,
        symbols: tuple[str, ...],
        version: int,
        bus: asyncio.Queue[tuple[Signal, float]],
        config: RuntimeConfig,
    ) -> int | None:
        self._on_universe_changed(symbols)
        stream_task = asyncio.create_task(self._stream_symbols(symbols, bus, config))
        update_task = asyncio.create_task(self.manager.wait_for_update(self.name, version))
        done, pending = await asyncio.wait(
            {stream_task, update_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if update_task in done:
            new_version = update_task.result()
            stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stream_task
            return new_version
        stream_task_result = None
        if stream_task in done:
            with contextlib.suppress(asyncio.CancelledError):
                stream_task_result = await stream_task
        update_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await update_task
        return stream_task_result

    def _on_universe_changed(self, symbols: Iterable[str]) -> None:
        ordered = tuple(dict.fromkeys(sym.upper() for sym in symbols))
        if len(ordered) > 80:
            self._log.warning(
                "[%s] trimming universe from %d to 80 symbols to satisfy stream limits",
                self.name,
                len(ordered),
            )
            ordered = ordered[:80]
        self._active_symbols = ordered

    async def _stream_symbols(
        self,
        symbols: tuple[str, ...],
        bus: asyncio.Queue[tuple[Signal, float]],
        config: RuntimeConfig,
    ) -> int | None:
        if not symbols:
            await asyncio.sleep(1.0)
            return None
        streams = "/".join(f"{sym.lower()}{self.stream_suffix}" for sym in symbols)
        url = self.endpoint.format(streams=streams)
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_queue=1024,
            ) as ws:
                self._log.debug("[%s] streaming %d symbols", self.name, len(symbols))
                async for raw in ws:
                    await self._handle_raw_message(raw, symbols, bus, config)
        except asyncio.CancelledError:
            raise
        except self._suppressed_errors as exc:
            self._log.warning("[%s] stream error: %s", self.name, exc, exc_info=True)
            await asyncio.sleep(3.0)
        return None

    async def _handle_raw_message(
        self,
        raw: str,
        symbols: tuple[str, ...],
        bus: asyncio.Queue[tuple[Signal, float]],
        config: RuntimeConfig,
    ) -> None:
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        symbol = str(data.get("s") or "").upper()
        if symbol not in self._active_symbols:
            return
        price_str = data.get("p") or data.get("c")
        if price_str is None:
            return
        try:
            price = float(price_str)
        except (TypeError, ValueError):
            return
        if price <= 0:
            return
        ts_ms = data.get("E") or data.get("T") or int(_now() * 1000)
        timestamp = float(ts_ms) / 1000.0
        await self._handle_tick(symbol, price, timestamp, bus, config)

    async def _handle_tick(
        self,
        symbol: str,
        price: float,
        ts: float,
        bus: asyncio.Queue[tuple[Signal, float]],
        config: RuntimeConfig,
    ) -> None:
        raise NotImplementedError


class TrendProducer(BaseStreamProducer):
    def __init__(self, config: RuntimeConfig, manager: UniverseManager) -> None:
        super().__init__("trend", manager)
        self.fast = 30
        self.slow = 120
        self.cooldown_seconds = 90.0
        self.ttl = float(config.bus.signal_ttl_seconds)
        self.history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.slow + 20))
        self.state: dict[str, str] = defaultdict(lambda: "flat")
        self.cooldown: dict[str, float] = defaultdict(float)

    def _on_universe_changed(self, symbols: Iterable[str]) -> None:
        super()._on_universe_changed(symbols)
        active = set(self._active_symbols)
        for key in list(self.history.keys()):
            if key not in active:
                self.history.pop(key, None)
                self.state.pop(key, None)
                self.cooldown.pop(key, None)

    async def _handle_tick(self, symbol: str, price: float, ts: float, bus, config):
        hist = self.history[symbol]
        hist.append(price)
        if len(hist) < self.slow:
            return
        if ts - self.cooldown.get(symbol, 0.0) < self.cooldown_seconds:
            return
        fast_ma = sum(list(hist)[-self.fast :]) / self.fast
        slow_ma = sum(list(hist)[-self.slow :]) / self.slow
        new_state = "long" if fast_ma > slow_ma else "short"
        if new_state == self.state.get(symbol):
            return
        self.state[symbol] = new_state
        self.cooldown[symbol] = ts
        side = "BUY" if new_state == "long" else "SELL"
        confidence = min(1.0, abs(fast_ma - slow_ma) / max(price, 1e-9) * 12.0)
        stop = price * (0.996 if side == "BUY" else 1.004)
        take_profit = price * (1.010 if side == "BUY" else 0.990)
        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            venue_hint="futures",
            stop=stop,
            take_profit=take_profit,
            ttl=self.ttl,
            meta={
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "price": price,
            },
        )
        await self._publish(bus, signal)


class MomentumProducer(BaseStreamProducer):
    def __init__(self, config: RuntimeConfig, manager: UniverseManager) -> None:
        super().__init__("momentum", manager)
        self.window_seconds = 90.0
        self.threshold = 0.005
        self.cooldown_seconds = 75.0
        self.ttl = float(config.bus.signal_ttl_seconds)
        self.history: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=600))
        self.last_signal: dict[str, float] = defaultdict(float)

    def _on_universe_changed(self, symbols: Iterable[str]) -> None:
        super()._on_universe_changed(symbols)
        active = set(self._active_symbols)
        for key in list(self.history.keys()):
            if key not in active:
                self.history.pop(key, None)
                self.last_signal.pop(key, None)

    async def _handle_tick(self, symbol: str, price: float, ts: float, bus, config):
        hist = self.history[symbol]
        hist.append((ts, price))
        while hist and ts - hist[0][0] > self.window_seconds:
            hist.popleft()
        if len(hist) < 2:
            return
        base_ts, base_price = hist[0]
        if base_price <= 0:
            return
        pct_change = (price / base_price) - 1.0
        if abs(pct_change) < self.threshold:
            return
        if ts - self.last_signal.get(symbol, 0.0) < self.cooldown_seconds:
            return
        side = "BUY" if pct_change > 0 else "SELL"
        confidence = min(1.0, abs(pct_change) / self.threshold)
        stop = price * (0.9925 if side == "BUY" else 1.0075)
        take_profit = price * (1.015 if side == "BUY" else 0.985)
        self.last_signal[symbol] = ts
        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            venue_hint="futures",
            stop=stop,
            take_profit=take_profit,
            ttl=self.ttl,
            meta={
                "pct_change": pct_change,
                "lookback": ts - base_ts,
            },
        )
        await self._publish(bus, signal)


class ScalperProducer(BaseStreamProducer):
    def __init__(self, config: RuntimeConfig, manager: UniverseManager) -> None:
        super().__init__("scalper", manager)
        self.short_window = 8
        self.long_window = 40
        self.cooldown_seconds = 25.0
        self.ttl = max(30.0, float(config.bus.signal_ttl_seconds))
        self.history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.long_window))
        self.last_signal: dict[str, float] = defaultdict(float)

    def _on_universe_changed(self, symbols: Iterable[str]) -> None:
        # Prioritise majors if provided
        super()._on_universe_changed(symbols)
        if not self._active_symbols:
            self._active_symbols = ("BTCUSDT", "ETHUSDT")
        active = set(self._active_symbols)
        for key in list(self.history.keys()):
            if key not in active:
                self.history.pop(key, None)
                self.last_signal.pop(key, None)

    async def _handle_tick(self, symbol: str, price: float, ts: float, bus, config):
        hist = self.history[symbol]
        hist.append(price)
        if len(hist) < self.long_window:
            return
        if ts - self.last_signal.get(symbol, 0.0) < self.cooldown_seconds:
            return
        long_avg = sum(hist) / len(hist)
        short_avg = sum(list(hist)[-self.short_window :]) / self.short_window
        deviation = (price - long_avg) / max(price, 1e-9)
        if abs(deviation) < 0.0008:
            return
        side = "SELL" if deviation > 0 else "BUY"
        confidence = min(1.0, abs(deviation) / 0.0015)
        self.last_signal[symbol] = ts
        stop = price * (1.002 if side == "SELL" else 0.998)
        take_profit = price * (0.997 if side == "SELL" else 1.003)
        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            venue_hint="futures",
            stop=stop,
            take_profit=take_profit,
            ttl=self.ttl,
            meta={
                "deviation": deviation,
                "short_avg": short_avg,
                "long_avg": long_avg,
            },
        )
        await self._publish(bus, signal)


class VolatilityProducer(BaseStreamProducer):
    def __init__(self, config: RuntimeConfig, manager: UniverseManager) -> None:
        super().__init__("event", manager)
        self.endpoint = BINANCE_SPOT_STREAM
        self.stream_suffix = "@miniTicker"
        self.window_seconds = 300.0
        self.threshold = 0.02
        self.cooldown_seconds = 240.0
        self.ttl = max(180.0, float(config.bus.signal_ttl_seconds))
        self.history: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=1800)
        )
        self.last_signal: dict[str, float] = defaultdict(float)

    def _on_universe_changed(self, symbols: Iterable[str]) -> None:
        super()._on_universe_changed(symbols)
        active = set(self._active_symbols)
        for key in list(self.history.keys()):
            if key not in active:
                self.history.pop(key, None)
                self.last_signal.pop(key, None)

    async def _handle_tick(self, symbol: str, price: float, ts: float, bus, config):
        hist = self.history[symbol]
        hist.append((ts, price))
        while hist and ts - hist[0][0] > self.window_seconds:
            hist.popleft()
        if len(hist) < 2:
            return
        base_ts, base_price = hist[0]
        if base_price <= 0:
            return
        pct_change = (price / base_price) - 1.0
        if abs(pct_change) < self.threshold:
            return
        if ts - self.last_signal.get(symbol, 0.0) < self.cooldown_seconds:
            return
        side = "BUY" if pct_change > 0 else "SELL"
        venue_hint = "spot" if side == "BUY" else "margin"
        confidence = min(1.0, abs(pct_change) / self.threshold)
        stop = price * (0.985 if side == "BUY" else 1.015)
        take_profit = price * (1.03 if side == "BUY" else 0.97)
        self.last_signal[symbol] = ts
        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            venue_hint=venue_hint,
            stop=stop,
            take_profit=take_profit,
            ttl=self.ttl,
            meta={
                "event_change": pct_change,
                "window": ts - base_ts,
            },
        )
        await self._publish(bus, signal)
