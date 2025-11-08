from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from typing import List

import pandas as pd


def daterange(start: str, end: str) -> List[str]:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _simulate_day(symbol: str, day: str, model: str = "quarantine") -> str | None:
    hits_path = f"data/hits/{symbol}_{day}.parquet"
    feats_path = f"data/features/1m/{symbol}/{day}.parquet"
    if not os.path.exists(hits_path) or not os.path.exists(feats_path):
        return None
    hits = pd.read_parquet(hits_path)
    bars = pd.read_parquet(feats_path).set_index("ts").sort_index()
    out = []
    for h in hits.itertuples():
        ts = int(h.ts)
        idx = bars.index.searchsorted(ts)
        if idx >= len(bars.index):
            continue
        entry_ts = int(bars.index[min(idx + 1, len(bars.index) - 1)])
        entry_px = (
            float(bars.loc[entry_ts, "last"])
            if "last" in bars.columns
            else float(
                bars.loc[entry_ts, "vwap_dev"] * 0
                + bars.loc[entry_ts, "r60"] * 0
                + bars.loc[entry_ts, "spread_over_atr"] * 0
                + 1.0
            )
        )

        # ATR proxy
        atr = float(0.001 * entry_px)
        if "spread_over_atr" in bars.columns and bars.loc[entry_ts, "spread_over_atr"] > 0:
            atr = max(atr, float(bars.loc[entry_ts, "spread_over_atr"]) * 0.001 * entry_px)

        direction = +1 if h.situation != "parabolic_blowoff" else -1
        stop_mult = 1.8 if model == "quarantine" else 2.2
        stop = entry_px - direction * stop_mult * atr
        tp = entry_px + direction * 3.0 * atr

        hold_limit = 30 * 60  # 30 minutes
        exit_ts = None
        exit_px = None
        for ts2 in bars.index[idx + 1 :]:
            px = float(bars.loc[ts2, "last"]) if "last" in bars.columns else entry_px
            if direction == +1 and px >= tp:
                exit_ts, exit_px = int(ts2), float(tp)
                break
            if direction == -1 and px <= tp:
                exit_ts, exit_px = int(ts2), float(tp)
                break
            if direction == +1 and px <= stop:
                exit_ts, exit_px = int(ts2), float(stop)
                break
            if direction == -1 and px >= stop:
                exit_ts, exit_px = int(ts2), float(stop)
                break
            if int(ts2) - entry_ts >= hold_limit:
                exit_ts, exit_px = int(ts2), float(px)
                break
        if exit_ts is None:
            continue

        spread_over_atr = (
            float(bars.loc[entry_ts, "spread_over_atr"])
            if "spread_over_atr" in bars.columns
            else 0.0
        )
        slip_bps = max(5.0, 0.3 * spread_over_atr * 100.0)
        ret = direction * (exit_px - entry_px) / max(entry_px, 1e-9)
        ret -= slip_bps / 10_000.0
        out.append(
            dict(
                event_id=h.event_id,
                situation=h.situation,
                symbol=symbol,
                entry_ts=int(entry_ts),
                exit_ts=int(exit_ts),
                pnl_usd=float(ret * 100.0),  # probe $100 notionals
                hold_sec=int(exit_ts - entry_ts),
                filled=True,
                slip_bps=float(slip_bps),
            )
        )
    if not out:
        return None
    df = pd.DataFrame(out)
    os.makedirs("data/outcomes", exist_ok=True)
    outp = f"data/outcomes/{symbol}_{day}.parquet"
    df.to_parquet(outp, index=False)
    return outp


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulate execution for situation hits")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--range", required=True)
    ap.add_argument("--model", default="quarantine")
    args = ap.parse_args()

    start, end = args.range.split("..", 1)
    days = daterange(start, end)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    wrote = 0
    for sym in symbols:
        for day in days:
            out = _simulate_day(sym, day, args.model)
            if out:
                print(out)
                wrote += 1
    print(f"outcomes files: {wrote}")


if __name__ == "__main__":
    main()
