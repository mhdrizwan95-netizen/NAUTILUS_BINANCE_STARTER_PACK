#!/usr/bin/env python3
"""Offline backtest harness for the momentum breakout module."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from backtests.engine import BacktestEngine, FeedConfig
from engine.strategies.momentum_realtime import (
    MomentumRealtimeConfig,
    MomentumStrategyModule,
    load_momentum_rt_config,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backtest momentum strategy on local data")
    ap.add_argument("--symbol", required=True, help="Symbol, e.g. BTCUSDT")
    ap.add_argument("--data", required=True, help="Path to CSV/Parquet klines")
    ap.add_argument("--timeframe", default="1m", help="Dataset timeframe label")
    ap.add_argument("--quote", type=float, default=100.0, help="Quote exposure per signal")
    ap.add_argument("--allow-shorts", action="store_true", help="Allow short signals")
    ap.add_argument(
        "--output",
        default="backtests/results/momentum_backtest.json",
        help="Output JSON path",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    base_cfg: MomentumRealtimeConfig = load_momentum_rt_config()
    cfg = replace(
        base_cfg,
        enabled=True,
        dry_run=True,
        symbols=(args.symbol.upper(),),
        quote_usd=args.quote,
        allow_shorts=bool(args.allow_shorts),
    )

    module = MomentumStrategyModule(cfg)

    feed = FeedConfig(
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        path=Path(args.data),
        driver=True,
        volume_column="volume",
    )

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: module,
        patch_executor=True,
    )

    signals: list[dict] = []
    for step in engine.run():
        if not step.response:
            continue
        payload = dict(step.response)
        payload["ts"] = step.event.timestamp_ms
        payload["price"] = step.event.price
        payload["volume"] = step.event.volume
        signals.append(payload)

    orders = [asdict(order) for order in engine.recorded_orders]

    summary = {
        "symbol": args.symbol.upper(),
        "signals": len(signals),
        "buys": sum(1 for s in signals if s.get("side") == "BUY"),
        "sells": sum(1 for s in signals if s.get("side") == "SELL"),
        "orders_recorded": len(orders),
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "signals": signals, "orders": orders}, indent=2)
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
