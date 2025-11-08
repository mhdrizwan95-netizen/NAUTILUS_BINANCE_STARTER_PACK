#!/usr/bin/env python3
"""
Model Leaderboard — rank all backtest reports by performance metrics.

Automatically scans reports/ directory and ranks models by Sharpe, PnL, win rate, or drawdown.
Provides quantitative experiment tracking and governance decision support.

Usage:
  python scripts/model_leaderboard.py --metric sharpe      # Rank by Sharpe ratio
  python scripts/model_leaderboard.py --metric pnl_usd     # Rank by P&L
  python scripts/model_leaderboard.py --metric winrate     # Rank by win rate
  python scripts/model_leaderboard.py --top 5              # Show top 5
"""

import json
import argparse
import sys
from pathlib import Path
import pandas as pd
from tabulate import tabulate

REPORTS_DIR = Path("reports")


def load_reports() -> pd.DataFrame:
    """Load all backtest reports from reports directory."""
    rows = []
    for path in REPORTS_DIR.glob("backtest_*.json"):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            data["file"] = path.name
            rows.append(data)
        except Exception as e:
            print(f"⚠️ Failed to load {path}: {e}", file=sys.stderr)
    if not rows:
        raise SystemExit(f"No reports found in {REPORTS_DIR}")
    return pd.DataFrame(rows)


def rank_models(metric: str, top: int = 10, ascending: bool = False) -> None:
    """Rank and display models by specified metric."""
    df = load_reports()

    if metric not in df.columns:
        available = ", ".join(df.columns)
        raise SystemExit(f"Metric '{metric}' not in reports (available: {available})")

    # Determine sorting direction
    if ascending is False:  # User didn't specify, determine from metric
        ascending = (
            "drawdown" in metric.lower()
            or metric.lower().endswith("_dd")
            or "max_" in metric.lower()
        )

    df_sorted = df.sort_values(metric, ascending=ascending).reset_index(drop=True)
    df_sorted["rank"] = range(1, len(df_sorted) + 1)

    # Format key columns for display
    display_cols = ["rank", "file", "symbol", metric]

    # Add contextual performance columns
    context_cols = []
    if metric != "sharpe" and "sharpe" in df.columns:
        context_cols.append("sharpe")
    if metric != "winrate" and "winrate" in df.columns:
        context_cols.append("winrate")
    if metric != "max_drawdown_usd" and "max_drawdown_usd" in df.columns:
        context_cols.append("max_drawdown_usd")
    if "trades" in df.columns:
        context_cols.append("trades")

    display_cols.extend(context_cols)

    # Display formatted table
    top_df = df_sorted.head(top)[display_cols]
    if not top_df.empty:
        print(tabulate(top_df, headers="keys", tablefmt="github", floatfmt=".4f"))

        # Show winner details
        best = df_sorted.iloc[0]
        best[metric]
        symbol = best.get("symbol", "N/A")

        print(f"\n🏆 Best Model: {best['file']}")
        print(f"   Strategy: {best.get('strategy', 'N/A')}")
        print(f"   Symbol: {symbol}")
        print(".4f")
        print(f"   Sharpe: {best.get('sharpe', 'N/A')}")
        print(".1%")
        print("4.2f")
        print(f"   Trades: {best.get('trades', 'N/A')}")

        # Show performance summary
        total_models = len(df_sorted)
        print(f"\n📊 Benchmark Summary ({total_models} models)")
        print(f"   Mean {metric}: {df[metric].mean():.4f}")
        print(f"   Best {metric}: {df[metric].max() if not ascending else df[metric].min():.4f}")
        print(f"   Std {metric}: {df[metric].std():.4f}")
    else:
        print("No models to display")


def main():
    ap = argparse.ArgumentParser(description="Rank model performance across all backtest reports")
    ap.add_argument(
        "--metric",
        default="sharpe",
        help="Metric to rank by: sharpe, pnl_usd, winrate, max_drawdown_usd, trades",
    )
    ap.add_argument("--top", type=int, default=10, help="Number of top models to display")
    ap.add_argument(
        "--asc",
        action="store_true",
        help="Sort ascending (useful for drawdown metrics)",
    )

    args = ap.parse_args()

    try:
        rank_models(args.metric, args.top, args.asc)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
