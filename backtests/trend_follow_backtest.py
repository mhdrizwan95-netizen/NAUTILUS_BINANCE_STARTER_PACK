#!/usr/bin/env python3
"""Offline backtest harness for the TrendStrategyModule.

It fetches recent Binance klines (spot) for the configured timeframes,
replays them sequentially through TrendStrategyModule, and records the
resulting trades/PnL profile so we can validate parameter defaults
before going live.
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_right
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from engine.strategies.trend_follow import (
    TrendStrategyModule,
    load_trend_config,
)


API_BASE = "https://api.binance.com"


def fetch_klines(symbol: str, interval: str, limit: int) -> List[List[float]]:
    resp = httpx.get(
        f"{API_BASE}/api/v3/klines",
        params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected kline payload for {symbol} {interval}")
    return data


class SimClock:
    def __init__(self) -> None:
        self._now = 0.0

    def set(self, ts: float) -> None:
        self._now = float(ts)

    def time(self) -> float:
        return self._now


class OfflineKlineClient:
    def __init__(self, data: Dict[Tuple[str, str], List[List[float]]]):
        self._data = data
        self._closes = {
            key: [int(row[6]) for row in rows]
            for key, rows in data.items()
        }
        self._current_close: Dict[Tuple[str, str], int] = {}

    def set_close_time(self, symbol: str, interval: str, close_ms: int) -> None:
        self._current_close[(symbol, interval)] = close_ms

    def klines(self, symbol: str, interval: str, limit: int) -> List[List[float]]:
        key = (symbol, interval)
        rows = self._data.get(key, [])
        closes = self._closes.get(key) or []
        cursor = self._current_close.get(key)
        if cursor is None:
            subset = rows
        else:
            idx = bisect_right(closes, cursor)
            subset = rows[:idx]
        if len(subset) > limit:
            return subset[-limit:]
        return subset


def run_backtest(symbol: str, limit: int, output: Path) -> Dict:
    cfg = replace(
        load_trend_config(),
        enabled=True,
        dry_run=True,
        symbols=[symbol],
        fetch_limit=limit,
        refresh_sec=0,
    )
    tf_set = {cfg.primary.interval, cfg.secondary.interval, cfg.regime.interval}
    data: Dict[Tuple[str, str], List[List[float]]] = {}
    for interval in tf_set:
        data[(symbol, interval)] = fetch_klines(symbol, interval, limit)

    client = OfflineKlineClient(data)
    clock = SimClock()
    module = TrendStrategyModule(cfg, client=client, clock=clock)

    primary = data[(symbol, cfg.primary.interval)]
    min_idx = max(cfg.primary.slow + 5, cfg.secondary.slow + 5, cfg.regime.slow + 5)
    trades = []
    position = None
    equity = float(cfg.fallback_equity_usd)
    peak_equity = equity
    trough = equity

    for i in range(min_idx, len(primary)):
        close_time = int(primary[i][6])
        price = float(primary[i][4])
        for interval in tf_set:
            client.set_close_time(symbol, interval, close_time)
        clock.set(close_time / 1000.0)
        action = module.handle_tick(f"{symbol}.BINANCE", price, close_time / 1000.0)
        if not action:
            continue
        side = action["side"]
        quote = float(action.get("quote") or cfg.min_quote_usd)
        if side == "BUY" and position is None:
            position = {
                "entry_px": price,
                "entry_ts": close_time,
                "quote": quote,
            }
        elif side == "SELL" and position is not None:
            pnl_pct = (price - position["entry_px"]) / position["entry_px"]
            pnl_quote = quote * pnl_pct
            equity += pnl_quote
            peak_equity = max(peak_equity, equity)
            trough = min(trough, equity)
            trades.append({
                "entry_ts": position["entry_ts"],
                "exit_ts": close_time,
                "entry_px": position["entry_px"],
                "exit_px": price,
                "quote": quote,
                "pnl_pct": pnl_pct,
                "pnl_quote": pnl_quote,
            })
            position = None

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    dd = ((trough - peak_equity) / peak_equity) if peak_equity else 0.0

    summary = {
        "symbol": symbol,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win_pct": sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0.0,
        "avg_loss_pct": sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0,
        "equity_end": equity,
        "equity_start": cfg.fallback_equity_usd,
        "max_drawdown_pct": dd * 100,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": summary, "trades": trades}, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest TrendStrategyModule")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("backtests/results/trend_backtest.json"))
    args = parser.parse_args()

    summary = run_backtest(args.symbol.upper(), args.limit, args.output)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
