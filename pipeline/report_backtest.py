from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import List, Tuple

import numpy as np
import pandas as pd


def _load_outcomes(pattern: str) -> pd.DataFrame:
    paths = sorted(glob.glob(pattern))
    if not paths:
        return pd.DataFrame(columns=["symbol", "situation", "pnl_usd", "entry_ts", "exit_ts"])
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


def _max_drawdown(equity: np.ndarray) -> float:
    peak = -np.inf
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (peak - v)
        if dd > mdd:
            mdd = dd
    return float(mdd)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate simple backtest report from outcomes")
    ap.add_argument("--range", required=False, help="Range label for report directory")
    ap.add_argument("--pattern", default="data/outcomes/*.parquet")
    args = ap.parse_args()

    df = _load_outcomes(args.pattern)
    if df.empty:
        print("no outcomes found")
        return
    df = df.copy()
    df["ts"] = df["exit_ts"].astype(int)
    df = df.sort_values("ts")
    equity = (df["pnl_usd"].cumsum()).to_numpy()
    pnl_total = float(df["pnl_usd"].sum())
    wins = int((df["pnl_usd"] > 0).sum())
    n = int(len(df))
    win_rate = (wins / n) * 100.0 if n else 0.0
    sharpe = float(np.mean(df["pnl_usd"])) / (float(np.std(df["pnl_usd"])) + 1e-9) * (252 ** 0.5) if n else 0.0
    mdd = _max_drawdown(equity)

    label = args.range or datetime.utcnow().strftime("%Y-%m-%d")
    outdir = os.path.join("reports", label)
    os.makedirs(outdir, exist_ok=True)
    md = [
        f"# Backtest Report ({label})",
        "",
        f"- Trades: {n}",
        f"- Total PnL (USD on $100 notionals): {pnl_total:.2f}",
        f"- Win rate: {win_rate:.2f}%",
        f"- Sharpe (per-trade proxy): {sharpe:.2f}",
        f"- Max Drawdown (USD): {mdd:.2f}",
        "",
        "## By Situation",
    ]
    by_sit = df.groupby("situation")["pnl_usd"].agg(["count", "mean", "sum"]).reset_index()
    for _, r in by_sit.iterrows():
        md.append(f"- {r['situation']}: n={int(r['count'])} mean={float(r['mean']):.2f} sum={float(r['sum']):.2f}")
    with open(os.path.join(outdir, "index.md"), "w") as f:
        f.write("\n".join(md))
    print(os.path.join(outdir, "index.md"))


if __name__ == "__main__":
    main()
