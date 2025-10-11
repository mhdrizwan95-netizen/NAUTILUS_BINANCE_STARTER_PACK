#!/usr/bin/env python3
"""
Leaderboard Visualizer — plot equity curves and PnL histograms
for your top backtest reports.

Usage:
  python scripts/model_leaderboard_viz.py --metric sharpe --top 3
"""

import json, argparse, os, sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
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

def load_equity_csv(json_path: Path) -> pd.DataFrame | None:
    """Load corresponding equity CSV for a JSON report."""
    csv_path = json_path.with_suffix(".csv")
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, parse_dates=["date"], date_format="%Y-%m-%d %H:%M:%S")
        return df
    except Exception as e:
        print(f"⚠️ Failed to load equity CSV {csv_path}: {e}", file=os.sys.stderr)
        return None

def visualize(metric: str = "sharpe", top: int = 3) -> None:
    """Generate leaderboard and create visualizations."""
    # Load and rank reports
    df = load_reports()

    if metric not in df.columns:
        available = ", ".join(df.columns)
        raise SystemExit(f"Metric '{metric}' not in reports (available: {available})")

    # Determine sorting direction
    ascending = "drawdown" in metric.lower() or metric.lower().startswith("max_")
    df_sorted = df.sort_values(metric, ascending=ascending).reset_index(drop=True)
    df_sorted["rank"] = range(1, len(df_sorted) + 1)

    # Display leaderboard table
    display_cols = ["rank", "file", "symbol", metric]
    context_cols = []
    if metric != "sharpe" and "sharpe" in df.columns:
        context_cols.append("sharpe")
    if metric != "winrate" and "winrate" in df.columns:
        context_cols.append("winrate")
    if "max_drawdown_usd" in df.columns:
        context_cols.append("max_drawdown_usd")
    if "trades" in df.columns:
        context_cols.append("trades")
    display_cols.extend(context_cols)

    top_df = df_sorted.head(top)[display_cols]
    if not top_df.empty:
        print(tabulate(top_df, headers="keys", tablefmt="github", floatfmt=".4f"))
    else:
        print("No models to display")
        return

    # Get paths to equity CSVs for top models
    top_files = df_sorted.head(top)["file"].tolist()

    # ---- Equity Curves Plot ----
    plt.figure(figsize=(12, 8))
    curve_labels = []
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

    for i, fname in enumerate(top_files):
        json_path = REPORTS_DIR / fname
        equity_df = load_equity_csv(json_path)
        if equity_df is None:
            continue

        # Plot equity curve
        color = colors[i % len(colors)]
        label = fname.replace("backtest_", "").replace(".json", "")
        curve_labels.append(label)

        plt.plot(equity_df["date"], equity_df["equity_usd"],
                linewidth=2.5, alpha=0.9, color=color,
                label=f"{label} ({df_sorted.iloc[i][metric]:.3f})")

    if curve_labels:
        plt.title(f"Equity Curves - Top {len(curve_labels)} Models by {metric.capitalize()}",
                 fontsize=14, pad=20)
        plt.xlabel("Date", fontsize=12)
        plt.ylabel("Equity (USD)", fontsize=12)
        plt.legend(loc='upper left', fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        equity_plot_path = REPORTS_DIR / f"leaderboard_equity_top{top}_{metric}.png"
        plt.savefig(equity_plot_path, dpi=150, bbox_inches='tight')
        print(f"📈 Equity curves saved → {equity_plot_path}")
        plt.close()

    # ---- PnL Comparison Bar Chart ----
    plt.figure(figsize=(10, 6))

    pnl_data = df_sorted.head(top).copy()
    pnl_files = pnl_data["file"].str.replace("backtest_", "").str.replace(".json", "")

    bars = plt.bar(range(len(pnl_data)), pnl_data["pnl_usd"],
                  color='#4C72B0', alpha=0.8, edgecolor='black', linewidth=0.5)

    plt.title(f"PnL Comparison - Top {top} Models by {metric.capitalize()}",
             fontsize=14, pad=20)
    plt.xlabel("Model", fontsize=12)
    plt.ylabel("Realized PnL (USD)", fontsize=12)
    plt.xticks(range(len(pnl_data)), pnl_files, rotation=30, ha='right', fontsize=10)

    # Add value labels on bars
    for bar, pnl in zip(bars, pnl_data["pnl_usd"]):
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + (abs(height) * 0.02),
                ".2f",
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    plt.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()

    pnl_plot_path = REPORTS_DIR / f"leaderboard_pnl_top{top}_{metric}.png"
    plt.savefig(pnl_plot_path, dpi=150, bbox_inches='tight')
    print(f"📊 PnL histogram saved → {pnl_plot_path}")
    plt.close()

    # ---- Summary ----
    winner = df_sorted.iloc[0]
    print(f"\n🏆 Winner: {winner['file']}")
    print(f"   {metric.upper()}: {winner[metric]:.4f}")
    print(f"   Sharpe: {winner.get('sharpe', 'N/A')}")
    print(f"   Win Rate: {winner.get('winrate', 'N/A'):.1%}")
    print(".2f")
    print(f"   PnL: ${winner.get('pnl_usd', 0):.2f}")

def main():
    ap = argparse.ArgumentParser(description="Visualize leaderboard with equity curves and PnL")
    ap.add_argument("--metric", default="sharpe", help="Metric to rank by")
    ap.add_argument("--top", type=int, default=3, help="Number of top models to plot")
    args = ap.parse_args()

    try:
        visualize(args.metric, args.top)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
