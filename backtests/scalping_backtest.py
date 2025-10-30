#!/usr/bin/env python3
"""Offline backtest harness for the scalping module using local klines."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

from backtests.engine import BacktestEngine, FeedConfig

from engine.strategies.scalping import ScalpStrategyModule, load_scalp_config


class ScalpingAdapter:
    def __init__(self, module: ScalpStrategyModule, spread_bps: float, depth_usd: float) -> None:
        self.module = module
        self.spread_bps = spread_bps
        self.depth_usd = depth_usd

    def handle_tick(self, symbol: str, price: float, ts: float, volume: float | None = None):
        spread = price * (self.spread_bps / 10_000.0)
        bid = max(0.0, price - spread / 2.0)
        ask = price + spread / 2.0
        qty = self.depth_usd / max(price, 1e-9) / 2.0
        self.module.handle_book(symbol, bid, ask, qty, qty, ts=ts)
        return self.module.handle_tick(symbol, price, ts)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backtest scalping strategy on local data")
    ap.add_argument("--symbol", required=True, help="Symbol, e.g. BTCUSDT")
    ap.add_argument("--data", required=True, help="Path to CSV/Parquet klines")
    ap.add_argument("--timeframe", default="1m", help="Dataset timeframe label")
    ap.add_argument("--spread-bps", type=float, default=5.0, help="Synthetic orderbook spread in bps")
    ap.add_argument("--depth-usd", type=float, default=50_000.0, help="Synthetic depth per side in USD")
    ap.add_argument("--output", default="backtests/results/scalp_backtest.json", help="Output JSON path")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    cfg = replace(
        load_scalp_config(),
        enabled=True,
        dry_run=True,
        symbols=(args.symbol.upper(),),
        min_depth_usd=0.0,
        max_spread_bps=max(args.spread_bps * 1.5, 10.0),
    )

    module = ScalpStrategyModule(cfg)
    adapter = ScalpingAdapter(module, spread_bps=args.spread_bps, depth_usd=args.depth_usd)

    feed = FeedConfig(
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        path=Path(args.data),
        driver=True,
    )

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: adapter,
    )

    signals: List[Dict] = []
    for step in engine.run():
        if not step.response:
            continue
        payload = dict(step.response)
        payload["ts"] = step.event.timestamp_ms
        payload["price"] = step.event.price
        signals.append(payload)

    summary = {
        "symbol": args.symbol.upper(),
        "signals": len(signals),
        "buys": sum(1 for s in signals if s.get("side") == "BUY"),
        "sells": sum(1 for s in signals if s.get("side") == "SELL"),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "signals": signals}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

