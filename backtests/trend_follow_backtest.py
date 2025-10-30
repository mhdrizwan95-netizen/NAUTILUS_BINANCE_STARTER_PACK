#!/usr/bin/env python3
"""Offline backtest harness for the TrendStrategyModule using local data."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Dict

from backtests.engine import BacktestEngine, FeedConfig

from engine.strategies.trend_follow import TrendStrategyModule, load_trend_config


def _parse_data_map(pairs: list[str]) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Data mapping must be '<interval>=<path>', got '{item}'")
        interval, path = item.split("=", 1)
        interval = interval.strip()
        if not interval:
            raise ValueError(f"Invalid interval for mapping '{item}'")
        mapping[interval] = Path(path.strip())
    return mapping


def run_backtest(
    *,
    symbol: str,
    data_map: Dict[str, Path],
    warmup: int,
    output: Path,
) -> Dict:
    cfg = replace(
        load_trend_config(),
        enabled=True,
        dry_run=True,
        symbols=[symbol],
        fetch_limit=0,
        refresh_sec=0,
    )

    required = {cfg.primary.interval, cfg.secondary.interval, cfg.regime.interval}
    missing = required.difference(data_map)
    if missing:
        raise SystemExit(
            "Missing dataset for timeframes: " + ", ".join(sorted(missing))
        )

    feeds = [
        FeedConfig(
            symbol=symbol,
            timeframe=interval,
            path=data_map[interval],
            driver=(interval == cfg.primary.interval),
            warmup_bars=warmup,
        )
        for interval in sorted(required)
    ]

    engine = BacktestEngine(
        feeds=feeds,
        strategy_factory=lambda client, clock: TrendStrategyModule(cfg, client=client, clock=clock),
        patch_executor=True,
    )

    trades = []
    position = None
    equity = float(cfg.fallback_equity_usd)
    peak_equity = equity
    trough = equity

    for step in engine.run():
        event = step.event
        action = step.response
        if not action:
            continue
        side = action.get("side")
        quote = float(action.get("quote") or cfg.min_quote_usd)
        price = float(event.price)
        close_time = event.timestamp_ms

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
            trades.append(
                {
                    "entry_ts": position["entry_ts"],
                    "exit_ts": close_time,
                    "entry_px": position["entry_px"],
                    "exit_px": price,
                    "quote": quote,
                    "pnl_pct": pnl_pct,
                    "pnl_quote": pnl_quote,
                }
            )
            position = None

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    dd = ((trough - peak_equity) / peak_equity) if peak_equity else 0.0

    orders = [asdict(order) for order in engine.recorded_orders]

    summary = {
        "symbol": symbol,
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_win_pct": sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0.0,
        "avg_loss_pct": sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0,
        "equity_end": equity,
        "equity_start": cfg.fallback_equity_usd,
        "max_drawdown_pct": dd * 100,
        "orders_recorded": len(orders),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": summary, "trades": trades, "orders": orders}, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest TrendStrategyModule")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument(
        "--data",
        action="append",
        required=True,
        help="Mapping of interval=path to CSV/Parquet klines",
    )
    parser.add_argument("--warmup", type=int, default=200, help="Bars to skip before trading")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backtests/results/trend_backtest.json"),
    )
    args = parser.parse_args()

    data_map = _parse_data_map(args.data)
    summary = run_backtest(
        symbol=args.symbol.upper(),
        data_map=data_map,
        warmup=max(0, args.warmup),
        output=args.output,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

