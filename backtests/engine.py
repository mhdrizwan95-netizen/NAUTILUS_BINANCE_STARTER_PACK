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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

import math
from bisect import bisect_right

import pandas as pd


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
            key: [int(row[6]) for row in rows]
            for key, rows in data.items()
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


class BacktestEngine:
    """Load historical klines and replay them through a strategy."""

    def __init__(
        self,
        feeds: Sequence[FeedConfig],
        *,
        strategy_factory: Callable[[OfflineKlineClient, SimClock], Any],
        symbol_formatter: Optional[Callable[[str, str, str], str]] = None,
    ) -> None:
        if not feeds:
            raise ValueError("At least one feed configuration is required")
        self._feeds = list(feeds)
        self._symbol_formatter = symbol_formatter or (lambda sym, tf, venue: f"{sym}.{venue}")
        self._strategy_factory = strategy_factory

        self._clock = SimClock()
        self._data: Dict[tuple[str, str], List[List[float]]] = {}
        self._feed_states: List[_FeedState] = []
        self._events: List[BacktestEvent] = []

        self._load_feeds()
        self._client = OfflineKlineClient(self._data)

    @property
    def clock(self) -> SimClock:
        return self._clock

    @property
    def client(self) -> OfflineKlineClient:
        return self._client

    def run(self) -> Iterator[BacktestStep]:
        strategy = self._strategy_factory(self._client, self._clock)
        dispatch = self._resolve_dispatch(strategy)

        for event in self._events:
            self._advance_to(event.timestamp_ms)
            self._clock.set(event.timestamp_seconds)
            symbol = self._symbol_formatter(event.symbol, event.timeframe, event.venue)
            response = dispatch(symbol, event.price, event.timestamp_seconds, event.volume)
            yield BacktestStep(event=event, response=response)

    # ------------------------------------------------------------------
    # Internals

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
    for open_time, open_px, high, low, close, volume, ts_ms, quote_vol, trade_count, taker_base, taker_quote in zip(
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

