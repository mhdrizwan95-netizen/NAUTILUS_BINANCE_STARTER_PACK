from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import pytest

from backtests.engine import BacktestEngine, FeedConfig
from engine.core.event_bus import BUS
from engine.idempotency import CACHE
from engine.strategy import get_executor_override
from engine.strategies.momentum_realtime import MomentumRealtimeConfig, MomentumStrategyModule


def _write_feed(
    tmp_path: Path,
    prices: List[float],
    start_ts: int = 1_700_000_000_000,
    volumes: Optional[List[float]] = None,
    times: Optional[List[float]] = None,
) -> Path:
    rows = []
    ts = start_ts
    for idx, price in enumerate(prices):
        volume = volumes[idx] if volumes and idx < len(volumes) else 1.0
        if times and idx < len(times):
            close_time = int(start_ts + times[idx] * 1000)
            open_time = close_time - 60_000
        else:
            close_time = ts + 60_000
            open_time = ts
        rows.append(
            {
                "open_time": open_time,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
                "close_time": close_time,
            }
        )
        if not times or idx >= len(times):
            ts += 60_000
    frame = pd.DataFrame(rows)
    path = tmp_path / "feed.csv"
    frame.to_csv(path, index=False)
    return path


def _subscribe() -> Tuple[List[Dict[str, float]], Callable[[Dict[str, float]], None]]:
    captured: List[Dict[str, float]] = []

    async def _handler(evt: Dict[str, float]) -> None:
        captured.append(evt)

    BUS.subscribe("trade.fill", _handler)
    return captured, _handler


def _unsubscribe(handler: Callable) -> None:
    try:
        BUS.unsubscribe("trade.fill", handler)
    except Exception:
        pass


class MarketOrderStrategy:
    def __init__(self, *, stop_mult: float = 0.98, take_mult: float = 1.02) -> None:
        self._sent = False
        self._entry_price: Optional[float] = None
        self._stop_mult = stop_mult
        self._take_mult = take_mult

    def handle_tick(self, symbol: str, price: float, ts: float, volume: float) -> None:
        executor = get_executor_override()
        if self._sent or not executor:
            return None
        self._sent = True
        self._entry_price = price
        stop_price = price * self._stop_mult
        take_profit = price * self._take_mult
        executor.execute_sync(
            {
                "strategy": "test",
                "symbol": symbol,
                "side": "BUY",
                "quantity": 1.0,
                "quote": None,
                "dry_run": False,
                "tag": "test_entry",
                "meta": {"stop_price": stop_price, "take_profit": take_profit},
                "market": "spot",
                "ts": ts,
            }
        )
        return None


class PendingExitStrategy:
    def __init__(self) -> None:
        self._step = 0
        self._entry_price: Optional[float] = None
        self._exit_id: Optional[str] = None

    def handle_tick(self, symbol: str, price: float, ts: float, volume: float) -> None:
        executor = get_executor_override()
        if not executor:
            return None
        self._step += 1
        if self._step == 1:
            self._entry_price = price
            executor.execute_sync(
                {
                    "strategy": "test",
                    "symbol": symbol,
                    "side": "BUY",
                    "quantity": 2.0,
                    "quote": None,
                    "dry_run": False,
                    "tag": "entry_long",
                    "meta": {
                        "stop_price": price * 0.97,
                        "take_profit": price * 1.03,
                    },
                    "market": "spot",
                    "ts": ts,
                }
            )
        elif self._step == 2 and self._entry_price is not None:
            executor.execute_sync(
                {
                    "strategy": "test",
                    "symbol": symbol,
                    "side": "SELL",
                    "quantity": 2.0,
                    "quote": None,
                    "dry_run": False,
                    "tag": "exit_tp",
                    "meta": {
                        "trigger": "tp",
                        "stop_price": self._entry_price * 0.97,
                        "take_profit": self._entry_price * 1.03,
                    },
                    "market": "spot",
                    "ts": ts,
                }
            )
        return None


class RapidVolStrategy:
    def __init__(self) -> None:
        self._step = 0

    def handle_tick(self, symbol: str, price: float, ts: float, volume: float) -> None:
        executor = get_executor_override()
        if not executor:
            return None
        self._step += 1
        if self._step == 1:
            for tag in ("entry_a", "entry_b"):
                executor.execute_sync(
                    {
                        "strategy": tag,
                        "symbol": symbol,
                        "side": "BUY",
                        "quantity": 1.0,
                        "quote": None,
                        "dry_run": False,
                        "tag": tag,
                        "meta": {"stop_price": price * 0.95, "take_profit": price * 1.02},
                        "market": "spot",
                        "ts": ts,
                    }
                )
        elif self._step == 2:
            executor.execute_sync(
                {
                    "strategy": "exit_a",
                    "symbol": symbol,
                    "side": "SELL",
                    "quantity": 1.0,
                    "quote": None,
                    "dry_run": False,
                    "tag": "exit_a_tp",
                    "meta": {
                        "trigger": "tp",
                        "stop_price": price * 0.9,
                        "take_profit": price * 1.05,
                    },
                    "market": "spot",
                    "ts": ts,
                }
            )
            executor.execute_sync(
                {
                    "strategy": "exit_b",
                    "symbol": symbol,
                    "side": "SELL",
                    "quantity": 1.0,
                    "quote": None,
                    "dry_run": False,
                    "tag": "exit_b_sl",
                    "meta": {
                        "trigger": "sl",
                        "stop_price": price * 1.01,
                        "take_profit": price * 0.9,
                    },
                    "market": "spot",
                    "ts": ts,
                }
            )
        return None


class MomentumExecutor:
    def __init__(self, module: MomentumStrategyModule) -> None:
        self._module = module

    def handle_tick(self, symbol: str, price: float, ts: float, volume: float) -> None:
        decision = self._module.handle_tick(symbol, price, ts, volume)
        if not decision:
            return None
        executor = get_executor_override()
        if not executor:
            return None
        executor.execute_sync(
            {
                "strategy": decision.get("tag", "momentum"),
                "symbol": decision.get("symbol", symbol),
                "side": decision.get("side", "BUY"),
                "quantity": None,
                "quote": decision.get("quote"),
                "dry_run": False,
                "tag": decision.get("tag"),
                "meta": decision.get("meta"),
                "market": decision.get("market"),
                "ts": ts,
            }
        )
        return decision


@pytest.mark.parametrize("strategy_cls", [MarketOrderStrategy])
def test_market_order_fill_emitted(tmp_path, strategy_cls):
    path = _write_feed(tmp_path, [100.0, 101.0, 102.0])
    feed = FeedConfig(symbol="TEST", timeframe="1m", path=path)
    strategy = strategy_cls()
    captured, handler = _subscribe()

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: strategy,
        patch_executor=True,
    )

    list(engine.run())

    _unsubscribe(handler)

    assert captured, "Expected at least one synthetic fill"
    entry = captured[0]
    assert entry["strategy_tag"] == "test_entry"
    assert math.isclose(entry["filled_qty"], 1.0)
    assert math.isclose(entry["avg_price"], 100.0)


def test_exit_fill_waits_for_trigger(tmp_path):
    path = _write_feed(tmp_path, [100.0, 100.5, 103.5])
    feed = FeedConfig(symbol="EXIT", timeframe="1m", path=path)
    strategy = PendingExitStrategy()
    captured, handler = _subscribe()

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: strategy,
        patch_executor=True,
    )

    list(engine.run())
    _unsubscribe(handler)

    assert len(captured) == 2
    entry, exit_evt = captured
    assert entry["strategy_tag"] == "entry_long"
    assert exit_evt["strategy_tag"] == "exit_tp"
    assert exit_evt["ts"] > entry["ts"]
    assert math.isclose(exit_evt["avg_price"], 103.5)


def test_multiple_fills_in_rapid_sequence(tmp_path):
    path = _write_feed(tmp_path, [50.0, 51.0, 55.0])
    feed = FeedConfig(symbol="FAST", timeframe="1m", path=path)
    strategy = RapidVolStrategy()
    captured, handler = _subscribe()

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: strategy,
        patch_executor=True,
    )

    list(engine.run())
    _unsubscribe(handler)

    tags = [evt["strategy_tag"] for evt in captured]
    assert tags.count("entry_a") == 1
    assert tags.count("entry_b") == 1
    assert "exit_a_tp" in tags
    assert "exit_b_sl" in tags
    assert len(captured) == 4


def test_momentum_signal_emits_fill(tmp_path):
    volumes = [40.0, 45.0, 220.0, 210.0]
    prices = [100.0, 100.6, 103.2, 104.0]
    times = [0.0, 35.0, 65.0, 80.0]
    path = _write_feed(tmp_path, prices, volumes=volumes, times=times)
    feed = FeedConfig(symbol="MOMO", timeframe="1m", path=path)

    cfg = MomentumRealtimeConfig(
        enabled=True,
        dry_run=True,
        symbols=("MOMO",),
        window_sec=30.0,
        baseline_sec=120.0,
        min_ticks=2,
        pct_move_threshold=0.02,
        volume_spike_ratio=1.5,
        cooldown_sec=60.0,
        quote_usd=100.0,
        stop_loss_pct=0.01,
        trail_pct=0.015,
        take_profit_pct=0.04,
        allow_shorts=False,
        prefer_futures=True,
    )

    module = MomentumStrategyModule(cfg)
    strategy = MomentumExecutor(module)
    captured, handler = _subscribe()

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: strategy,
        patch_executor=True,
    )

    list(engine.run())
    _unsubscribe(handler)

    assert captured
    tags = {evt["strategy_tag"] for evt in captured}
    assert any(tag.startswith("momentum_rt") for tag in tags)

@pytest.fixture(autouse=True)
def _clear_idempotency_cache():
    CACHE.cache.clear()
    yield
    CACHE.cache.clear()

