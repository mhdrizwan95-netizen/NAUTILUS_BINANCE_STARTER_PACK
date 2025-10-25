from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime, timedelta
from typing import Iterable, List

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from screener.features import compute_feats as live_compute


def daterange(start: str, end: str) -> List[str]:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _build_day(symbol: str, day: str, src_root: str = "data/raw/binance/spot/1m", dst_root: str = "data/features/1m") -> str | None:
    year = day[:4]
    src = f"{src_root}/{symbol}/{year}/{day}.parquet"
    if not os.path.exists(src):
        return None
    raw = pq.read_table(src).to_pandas()
    feats = []
    # rolling window of 60 bars to match live feature assumptions
    for i in range(60, len(raw)):
        window = raw.iloc[i - 60 : i + 1]
        # construct minimal klines used by live_compute (indexes 4=close,5=volume)
        kl = [[None, None, None, None, str(x.close), str(x.volume)] for x in window.itertuples()]
        last = float(window.close.iloc[-1])
        # use a simple spread proxy (5 bps) if no depth available
        book = {"bids": [[last * 0.9995, 1.0]], "asks": [[last * 1.0005, 1.0]]}
        f = live_compute(kl, book)
        f["ts"] = int(window.ts.iloc[-1])
        feats.append(f)
    if not feats:
        return None
    df = pd.DataFrame(feats)
    out = f"{dst_root}/{symbol}/{day}.parquet"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_parquet(out, index=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build offline features from raw Parquet")
    ap.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT")
    ap.add_argument("--range", required=True, help="YYYY-MM-DD..YYYY-MM-DD inclusive")
    args = ap.parse_args()

    start, end = args.range.split("..", 1)
    days = daterange(start, end)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    built = []
    for sym in symbols:
        for day in days:
            out = _build_day(sym, day)
            if out:
                built.append(out)
                print(out)
    print(f"built: {len(built)} files")


if __name__ == "__main__":
    main()
