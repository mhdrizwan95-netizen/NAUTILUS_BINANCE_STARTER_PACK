"""Generic offline replay engine for strategy backtests.

The goal of this module is to provide a single, reusable event loop that
behaves similarly to the live runtime: it loads historical candles (klines)
from CSV/Parquet files, replays them in chronological order, and invokes the
configured strategy's tick handler (``handle_tick`` or ``on_tick``).

Individual backtest scripts can focus on position/PnL accounting while this
engine deals with file loading, warmup offsets, multi-symbol/timeframe
coordination, and simple clock/client shims that match what the production
code expects.
"""

from __future__ import annotations

import asyncio
import math
import os
import threading
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

import pandas as pd

from engine.core.event_bus import BUS
from engine.execution.execute import RecordedOrder, StrategyExecutor
from engine.runtime import tasks as runtime_tasks
from engine.strategy import (
    get_executor_override,
    reset_executor_cache,
    set_executor_override,
)

# ---------------------------------------------------------------------------
# Utility shims used by several backtests


class SimClock:
    """Minimal clock interface compatible with the live runtime."""

    def __init__(self) -> None:
        self._now = 0.0

    def set(self, ts: float) -> None:
        self._now = float(ts)

    def time(self) -> float:
        return self._now


class OfflineKlineClient:
    """Local-only kline reader that mimics the sync client contract."""

    def __init__(self, data: Dict[tuple[str, str], List[List[float]]]):
        self._data = data
        self._closes: Dict[tuple[str, str], List[int]] = {
            key: [int(row[6]) for row in rows] for key, rows in data.items()
        }
        self._cursor: Dict[tuple[str, str], int] = {}

    def set_close_time(self, symbol: str, interval: str, close_ms: int) -> None:
        self._cursor[(symbol, interval)] = close_ms

    def klines(self, symbol: str, interval: str, limit: int) -> List[List[float]]:
        key = (symbol, interval)
        rows = self._data.get(key, [])
        closes = self._closes.get(key) or []
        cursor = self._cursor.get(key)
        if cursor is None:
            subset = rows
        else:
            idx = bisect_right(closes, cursor)
            subset = rows[:idx]
        if len(subset) > limit:
            return subset[-limit:]
        return subset


# ---------------------------------------------------------------------------
# Feed configuration and event plumbing


@dataclass(frozen=True)
class FeedConfig:
    """Describes a single symbol/timeframe data source."""

    symbol: str
    timeframe: str
    path: Path
    venue: str = "BINANCE"
    driver: bool = True
    warmup_bars: int = 0
    timestamp_column: str = "close_time"
    price_column: str = "close"
    volume_column: str = "volume"


@dataclass(frozen=True)
class BacktestEvent:
    """A single replay event corresponding to a candle close."""

    symbol: str
    timeframe: str
    venue: str
    price: float
    volume: float
    timestamp_ms: int
    index: int

    @property
    def timestamp_seconds(self) -> float:
        if self.timestamp_ms > 1_000_000_000_000:
            return self.timestamp_ms / 1000.0
        return float(self.timestamp_ms)


@dataclass
class BacktestStep:
    event: BacktestEvent
    response: Any


@dataclass
class _OpenPosition:
    symbol: str
    venue: str
    side: str
    quantity: float
    stop_price: Optional[float]
    take_profit: Optional[float]
    tag: str
    order_id: str


@dataclass
class _PendingExit:
    order: RecordedOrder
    base: str
    venue: str
    quantity: float
    trigger: Optional[str]
    stop_price: Optional[float]
    take_profit: Optional[float]
    strategy_symbol: str
    meta: Optional[Dict[str, Any]]
    recorded_ts: float
    recorded_price: float


class _AsyncBusRunner:
    def __init__(self, bus) -> None:
        self._bus = bus
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        if getattr(self._bus, "_running", False):
            self._started = True
            return
        executor = getattr(self._bus, "_executor", None)
        if executor and getattr(executor, "_shutdown", False):
            max_workers = getattr(executor, "_max_workers", 8)
            self._bus._executor = ThreadPoolExecutor(max_workers=max_workers)
        loop = asyncio.new_event_loop()
        self._loop = loop

        def _runner() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=_runner, name="backtest-bus", daemon=True)
        self._thread = thread
        thread.start()
        try:
            fut = asyncio.run_coroutine_threadsafe(self._bus.start(), loop)
            fut.result()
            self._started = True
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self._started:
            return
        loop = self._loop
        thread = self._thread
        self._started = False
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._bus.stop(), loop).result(timeout=2)
        except Exception:
            pass
        try:
            asyncio.run_coroutine_threadsafe(runtime_tasks.shutdown(), loop).result(timeout=2)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if thread:
            thread.join(timeout=2)
        loop.close()
        self._loop = None
        self._thread = None
        try:
            self._bus.shutdown(wait=True)
        except Exception:
            pass

    def publish(self, topic: str, payload: Dict[str, Any]) -> Optional[asyncio.Future]:
        loop = self._loop
        if not getattr(self._bus, "_running", False):
            return None
        if loop is None:
            self._bus.fire(topic, payload)
            return None
        return asyncio.run_coroutine_threadsafe(
            self._bus.publish(topic, payload, urgent=True), loop
        )


class _SyntheticFillSimulator:
    def __init__(self, *, clock: SimClock) -> None:
        self._clock = clock
        self._bus_runner = _AsyncBusRunner(BUS)
        self._last_prices: Dict[tuple[str, str], float] = {}
        self._open_positions: Dict[tuple[str, str, str], List[_OpenPosition]] = defaultdict(list)
        self._pending_exits: List[_PendingExit] = []

    @contextmanager
    def lifecycle(self):
        self._bus_runner.start()
        try:
            yield
        finally:
            self._pending_exits.clear()
            self._open_positions.clear()
            self._last_prices.clear()
            self._bus_runner.stop()

    def on_price_event(self, event: BacktestEvent) -> None:
        base = event.symbol.upper()
        venue = event.venue.upper()
        price = float(event.price)
        ts = event.timestamp_seconds
        self._last_prices[(base, venue)] = price
        triggered: List[_PendingExit] = []
        for pending in list(self._pending_exits):
            if pending.base != base or pending.venue != venue:
                continue
            if self._exit_triggered(
                pending.order.side,
                pending.trigger,
                price,
                pending.stop_price,
                pending.take_profit,
            ):
                triggered.append(pending)
        for pending in triggered:
            self._pending_exits.remove(pending)
            self._emit_fill(
                order=pending.order,
                base=base,
                venue=venue,
                side=pending.order.side,
                quantity=pending.quantity,
                price=price,
                ts=ts,
                strategy_symbol=pending.strategy_symbol,
                meta=pending.meta,
            )
            self._close_position(base, venue, pending.order.side, pending.quantity)

    def record_order(self, order: RecordedOrder, event: Optional[BacktestEvent]) -> None:
        if order is None:
            return
        if order.status not in {"backtest", "dry_run", "simulated"}:
            return
        base, venue = self._resolve_symbol(order.symbol, event)
        if base is None or venue is None:
            return
        price = self._resolve_price(base, venue, event)
        if price is None or price <= 0.0:
            return
        quantity = self._resolve_quantity(order, price)
        if quantity is None or quantity <= 0.0:
            return
        ts = event.timestamp_seconds if event else float(order.timestamp)
        strategy_symbol = order.symbol or f"{base}.{venue}"
        meta = order.meta if isinstance(order.meta, dict) else None
        trigger = self._infer_trigger(order.tag, meta)

        if trigger:
            stop_price = self._safe_float(meta.get("stop_price")) if meta else None
            take_profit = self._safe_float(meta.get("take_profit")) if meta else None
            if self._exit_triggered(order.side, trigger, price, stop_price, take_profit):
                self._emit_fill(
                    order,
                    base,
                    venue,
                    order.side,
                    quantity,
                    price,
                    ts,
                    strategy_symbol,
                    meta,
                )
                self._close_position(base, venue, order.side, quantity)
            else:
                pending = _PendingExit(
                    order=order,
                    base=base,
                    venue=venue,
                    quantity=quantity,
                    trigger=trigger,
                    stop_price=stop_price,
                    take_profit=take_profit,
                    strategy_symbol=strategy_symbol,
                    meta=dict(meta) if isinstance(meta, dict) else None,
                    recorded_ts=ts,
                    recorded_price=price,
                )
                self._pending_exits.append(pending)
        else:
            self._emit_fill(
                order,
                base,
                venue,
                order.side,
                quantity,
                price,
                ts,
                strategy_symbol,
                meta,
            )
            if meta:
                stop_price = self._safe_float(meta.get("stop_price"))
                take_profit = self._safe_float(meta.get("take_profit"))
            else:
                stop_price = None
                take_profit = None
            key = (base, venue, order.side.upper())
            position = _OpenPosition(
                symbol=base,
                venue=venue,
                side=order.side.upper(),
                quantity=quantity,
                stop_price=stop_price,
                take_profit=take_profit,
                tag=str(order.tag or ""),
                order_id=str(order.idempotency_key or ""),
            )
            self._open_positions[key].append(position)

    @staticmethod
    def _infer_trigger(tag: Optional[str], meta: Optional[Dict[str, Any]]) -> Optional[str]:
        if isinstance(meta, dict) and isinstance(meta.get("trigger"), str):
            return str(meta["trigger"]).lower()
        if not tag:
            return None
        lowered = tag.lower()
        if lowered.endswith("_tp") or lowered.endswith("tp"):
            return "tp"
        if lowered.endswith("_sl") or lowered.endswith("sl"):
            return "sl"
        if "exit" in lowered:
            return "exit"
        return None

    @staticmethod
    def _resolve_quantity(order: RecordedOrder, price: float) -> Optional[float]:
        quantity = order.quantity
        if quantity is not None:
            try:
                return abs(float(quantity))
            except Exception:
                return None
        quote = order.quote
        if quote is None or price <= 0.0:
            return None
        try:
            qty = float(quote) / price
        except Exception:
            return None
        return abs(qty)

    def _resolve_price(
        self, base: str, venue: str, event: Optional[BacktestEvent]
    ) -> Optional[float]:
        if event:
            return float(event.price)
        return self._last_prices.get((base, venue))

    @staticmethod
    def _resolve_symbol(
        symbol: Optional[str], event: Optional[BacktestEvent]
    ) -> tuple[Optional[str], Optional[str]]:
        if symbol and "." in symbol:
            base, venue = symbol.split(".", 1)
            return base.upper(), venue.upper()
        if symbol:
            return symbol.upper(), event.venue.upper() if event else "BINANCE"
        if event:
            return event.symbol.upper(), event.venue.upper()
        return None, None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            val = float(value)
        except Exception:
            return None
        return val if math.isfinite(val) else None

    def _emit_fill(
        self,
        order: RecordedOrder,
        base: str,
        venue: str,
        side: str,
        quantity: float,
        price: float,
        ts: float,
        strategy_symbol: str,
        meta: Optional[Dict[str, Any]],
    ) -> None:
        if quantity <= 0.0 or price <= 0.0:
            return
        payload: Dict[str, Any] = {
            "ts": ts,
            "symbol": base,
            "side": str(side or "").upper(),
            "venue": venue,
            "intent": str(order.tag or "GENERIC"),
            "order_id": str(order.idempotency_key or ""),
            "filled_qty": float(quantity),
            "avg_price": float(price),
            "strategy_tag": str(order.tag or ""),
            "strategy_side": str(side or "").upper(),
            "strategy_symbol": strategy_symbol,
        }
        if isinstance(meta, dict) and meta:
            payload["strategy_meta"] = dict(meta)
        fut = self._bus_runner.publish("trade.fill", payload)
        if fut is not None:
            try:
                fut.result(timeout=2)
            except Exception:
                pass

    def _close_position(self, base: str, venue: str, exit_side: str, quantity: float) -> None:
        entry_side = "BUY" if exit_side.upper() == "SELL" else "SELL"
        key = (base, venue, entry_side)
        positions = self._open_positions.get(key)
        if not positions:
            return
        index = None
        for idx, pos in enumerate(positions):
            if math.isclose(pos.quantity, quantity, rel_tol=1e-6, abs_tol=1e-9):
                index = idx
                break
        if index is None:
            index = 0
        positions.pop(index)
        if not positions:
            self._open_positions.pop(key, None)

    def _exit_triggered(
        self,
        side: str,
        trigger: Optional[str],
        price: float,
        stop_price: Optional[float],
        take_profit: Optional[float],
    ) -> bool:
        if price <= 0.0:
            return False
        side_u = str(side or "").upper()
        trigger_l = (trigger or "").lower()
        if side_u == "SELL":
            if trigger_l == "tp" and take_profit is not None:
                return price >= take_profit
            if trigger_l == "sl" and stop_price is not None:
                return price <= stop_price
            if trigger_l == "exit":
                conds = []
                if take_profit is not None:
                    conds.append(price >= take_profit)
                if stop_price is not None:
                    conds.append(price <= stop_price)
                return any(conds)
            if take_profit is not None and price >= take_profit:
                return True
            if stop_price is not None and price <= stop_price:
                return True
        else:  # BUY closes shorts
            if trigger_l == "tp" and take_profit is not None:
                return price <= take_profit
            if trigger_l == "sl" and stop_price is not None:
                return price >= stop_price
            if trigger_l == "exit":
                conds = []
                if take_profit is not None:
                    conds.append(price <= take_profit)
                if stop_price is not None:
                    conds.append(price >= stop_price)
                return any(conds)
            if take_profit is not None and price <= take_profit:
                return True
            if stop_price is not None and price >= stop_price:
                return True
        return False


class BacktestEngine:
    """Load historical klines and replay them through a strategy."""

    def __init__(
        self,
        feeds: Sequence[FeedConfig],
        *,
        strategy_factory: Callable[[OfflineKlineClient, SimClock], Any],
        symbol_formatter: Optional[Callable[[str, str, str], str]] = None,
        patch_executor: Optional[bool] = None,
        executor_factory: Optional[
            Callable[[Callable[[RecordedOrder], None]], StrategyExecutor]
        ] = None,
    ) -> None:
        if not feeds:
            raise ValueError("At least one feed configuration is required")
        self._feeds = list(feeds)
        self._symbol_formatter = symbol_formatter or (lambda sym, tf, venue: f"{sym}.{venue}")
        self._strategy_factory = strategy_factory
        self._patch_executor = self._resolve_patch_flag(patch_executor)
        self._executor_factory = executor_factory

        self._clock = SimClock()
        self._data: Dict[tuple[str, str], List[List[float]]] = {}
        self._feed_states: List[_FeedState] = []
        self._events: List[BacktestEvent] = []
        self._recorded_orders: List[RecordedOrder] = []
        self._active_event: Optional[BacktestEvent] = None
        self._fill_simulator = _SyntheticFillSimulator(clock=self._clock)

        self._load_feeds()
        self._client = OfflineKlineClient(self._data)

    @property
    def clock(self) -> SimClock:
        return self._clock

    @property
    def client(self) -> OfflineKlineClient:
        return self._client

    @property
    def recorded_orders(self) -> Sequence[RecordedOrder]:
        return tuple(self._recorded_orders)

    def run(self) -> Iterator[BacktestStep]:
        self._prime_cursors()
        with self._maybe_patched_executor():
            strategy = self._strategy_factory(self._client, self._clock)
            dispatch = self._resolve_dispatch(strategy)

            with self._fill_simulator.lifecycle():
                for event in self._events:
                    self._fill_simulator.on_price_event(event)
                    self._advance_to(event.timestamp_ms)
                    self._clock.set(event.timestamp_seconds)
                    symbol = self._symbol_formatter(event.symbol, event.timeframe, event.venue)
                    self._active_event = event
                    response = dispatch(symbol, event.price, event.timestamp_seconds, event.volume)
                    self._active_event = None
                    yield BacktestStep(event=event, response=response)

    # ------------------------------------------------------------------
    # Internals

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    def _resolve_patch_flag(self, patch_executor: Optional[bool]) -> bool:
        if patch_executor is not None:
            return bool(patch_executor)
        env_default = self._env_flag("BACKTEST_PATCH_EXECUTOR", False)
        env_fallback = self._env_flag("NAUTILUS_BACKTEST_EXECUTOR", env_default)
        return env_fallback

    def _maybe_patched_executor(self):
        @contextmanager
        def _noop():
            yield

        if not self._patch_executor:
            return _noop()

        return self._executor_context()

    def _executor_context(self):
        @contextmanager
        def _ctx():
            previous = get_executor_override()
            executor = self._build_executor()
            set_executor_override(executor)
            reset_executor_cache()
            try:
                yield
            finally:
                set_executor_override(previous)
                reset_executor_cache()

        return _ctx()

    def _build_executor(self) -> StrategyExecutor:
        factory = self._executor_factory or self._default_executor_factory
        return factory(self._record_order)

    def _record_order(self, order: RecordedOrder) -> None:
        self._recorded_orders.append(order)
        self._fill_simulator.record_order(order, self._active_event)

    @staticmethod
    def _default_executor_factory(
        recorder: Callable[[RecordedOrder], None],
    ) -> StrategyExecutor:
        class _PassthroughRisk:
            def check_order(self, **_: Any) -> tuple[bool, Dict[str, Any]]:  # type: ignore[override]
                return True, {}

        class _NullRouter:
            pass

        return StrategyExecutor(
            risk=_PassthroughRisk(),
            router=_NullRouter(),
            default_dry_run=True,
            source="backtest",
            backtest_mode=True,
            order_recorder=recorder,
        )

    def _load_feeds(self) -> None:
        for cfg in self._feeds:
            rows = _load_klines(cfg)
            if not rows:
                raise ValueError(f"No rows loaded for {cfg.symbol} {cfg.timeframe} from {cfg.path}")
            key = (cfg.symbol, cfg.timeframe)
            self._data[key] = rows
            state = _FeedState(cfg=cfg, rows=rows)
            self._feed_states.append(state)
            if cfg.driver:
                for idx in range(state.start_index, len(rows)):
                    row = rows[idx]
                    price = float(row[4])
                    volume = float(row[5]) if len(row) > 5 else 0.0
                    ts = int(row[6])
                    self._events.append(
                        BacktestEvent(
                            symbol=cfg.symbol,
                            timeframe=cfg.timeframe,
                            venue=cfg.venue,
                            price=price,
                            volume=volume,
                            timestamp_ms=ts,
                            index=idx,
                        )
                    )

        self._events.sort(key=lambda evt: (evt.timestamp_ms, evt.symbol, evt.timeframe))

    def _advance_to(self, timestamp_ms: int) -> None:
        for state in self._feed_states:
            closes = state.close_times
            next_index = state.cursor + 1
            while next_index < len(closes) and closes[next_index] <= timestamp_ms:
                state.cursor = next_index
                next_index += 1
            if state.cursor >= 0:
                self._client.set_close_time(
                    state.cfg.symbol,
                    state.cfg.timeframe,
                    closes[state.cursor],
                )
            elif closes:
                # If we have never advanced, clamp the cursor to just before the
                # first candle so clients still see an empty history.
                self._client.set_close_time(
                    state.cfg.symbol,
                    state.cfg.timeframe,
                    closes[0] - 1,
                )

    def _prime_cursors(self) -> None:
        for state in self._feed_states:
            if not state.close_times:
                continue
            idx, ts = state.initial_cursor()
            state.cursor = idx
            self._client.set_close_time(state.cfg.symbol, state.cfg.timeframe, ts)

    @staticmethod
    def _resolve_dispatch(strategy: Any) -> Callable[[str, float, float, float], Any]:
        for attr in ("handle_tick", "on_tick"):
            if hasattr(strategy, attr):
                fn = getattr(strategy, attr)

                def _call(symbol: str, price: float, ts: float, volume: float) -> Any:
                    try:
                        return fn(symbol, price, ts, volume)
                    except TypeError:
                        return fn(symbol, price, ts)

                return _call
        raise AttributeError("Strategy does not expose handle_tick or on_tick")


class _FeedState:
    def __init__(self, cfg: FeedConfig, rows: List[List[float]]) -> None:
        self.cfg = cfg
        self.rows = rows
        self.close_times = [int(row[6]) for row in rows]
        self.cursor = -1
        self.start_index = min(len(rows), max(0, cfg.warmup_bars))

    def initial_cursor(self) -> tuple[int, int]:
        """Return the starting index and timestamp visible before the first event."""

        if not self.close_times:
            return -1, 0

        if self.start_index <= 0:
            # No warmup bars, expose an empty history until the first event.
            return -1, self.close_times[0] - 1

        idx = min(self.start_index, len(self.close_times)) - 1
        return idx, self.close_times[idx]


# ---------------------------------------------------------------------------
# Helpers


def _load_klines(cfg: FeedConfig) -> List[List[float]]:
    path = cfg.path
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() in {".parquet", ".pq"}:
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path)

    if frame.empty:
        return []

    cols = {c.lower(): c for c in frame.columns}

    def resolve(names: Iterable[str]) -> str:
        for name in names:
            key = name.lower()
            if key in cols:
                return cols[key]
        raise KeyError(f"Missing required column. Tried {names} in {path}")

    def optional(names: Iterable[str], fallback: Optional[str] = None) -> str:
        for name in names:
            key = name.lower()
            if key in cols:
                return cols[key]
        if fallback is None:
            name = next(iter(names))
            frame[name] = 0.0
            cols[name.lower()] = name
            return name
        return fallback

    ts_col = resolve([cfg.timestamp_column, "close_time", "ts", "timestamp"])
    price_col = resolve([cfg.price_column, "close", "price"])
    volume_col = optional([cfg.volume_column, "volume"], fallback="volume")
    if volume_col == "volume" and "volume" not in frame.columns:
        frame[volume_col] = 0.0
        cols["volume"] = volume_col

    open_col = optional(["open_time", "open_ts", "start_time"], fallback=ts_col)
    open_price_col = optional(["open"], fallback=price_col)
    high_col = optional(["high"], fallback=price_col)
    low_col = optional(["low"], fallback=price_col)

    trade_count_col = cols.get("number_of_trades") or cols.get("trade_count")
    if trade_count_col is None:
        trade_count_col = "trade_count"
        frame[trade_count_col] = 0
        cols["trade_count"] = trade_count_col

    taker_base_col = cols.get("taker_buy_base") or cols.get("taker_buy_volume")
    if taker_base_col is None:
        taker_base_col = "taker_buy_volume"
        frame[taker_base_col] = frame[volume_col]
        cols["taker_buy_volume"] = taker_base_col

    taker_quote_col = cols.get("taker_buy_quote") or cols.get("taker_buy_quote_volume")
    if taker_quote_col is None:
        taker_quote_col = "taker_buy_quote_volume"
        frame[taker_quote_col] = frame[price_col]
        cols["taker_buy_quote_volume"] = taker_quote_col

    quote_volume_col = cols.get("quote_volume") or cols.get("quote_asset_volume")
    if quote_volume_col is None:
        quote_volume_col = "quote_volume"
        frame[quote_volume_col] = frame[price_col] * frame[volume_col]
        cols["quote_volume"] = quote_volume_col

    frame = frame.sort_values(ts_col).reset_index(drop=True)

    ts_series = frame[ts_col].astype(float)
    if ts_series.max() < 1_000_000_000_000:
        frame[ts_col] = (ts_series * 1000.0).astype(int)
    else:
        frame[ts_col] = ts_series.astype(int)

    rows: List[List[float]] = []
    for (
        open_time,
        open_px,
        high,
        low,
        close,
        volume,
        ts_ms,
        quote_vol,
        trade_count,
        taker_base,
        taker_quote,
    ) in zip(
        frame[open_col].astype(float),
        frame[open_price_col].astype(float),
        frame[high_col].astype(float),
        frame[low_col].astype(float),
        frame[price_col].astype(float),
        frame[volume_col].astype(float),
        frame[ts_col].astype(int),
        frame[quote_volume_col].astype(float),
        frame[trade_count_col].astype(float),
        frame[taker_base_col].astype(float),
        frame[taker_quote_col].astype(float),
    ):
        if not math.isfinite(close) or not math.isfinite(ts_ms):
            continue
        rows.append(
            [
                float(open_time),
                float(open_px),
                float(high),
                float(low),
                float(close),
                float(volume),
                int(ts_ms),
                float(quote_vol),
                float(trade_count),
                float(taker_base),
                float(taker_quote),
                0.0,
            ]
        )

    return rows


__all__ = [
    "BacktestEngine",
    "BacktestEvent",
    "BacktestStep",
    "FeedConfig",
    "OfflineKlineClient",
    "SimClock",
]
