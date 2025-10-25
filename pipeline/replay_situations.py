from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd

from situations.matcher import Matcher
from situations.schema import Situation


def daterange(start: str, end: str) -> List[str]:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _load_situations(path: str = "config/situations.json") -> Dict[str, Situation]:
    data = json.loads(open(path).read())
    return {s["name"]: Situation(**s) for s in data}


def replay(symbol: str, day: str, feats_root: str = "data/features/1m", out_root: str = "data/hits") -> str | None:
    src = f"{feats_root}/{symbol}/{day}.parquet"
    if not os.path.exists(src):
        return None
    feats = pd.read_parquet(src)
    store = type("Store", (), {})()
    store.sits = _load_situations()
    store.active = lambda: list(store.sits.values())
    M = Matcher(store)
    hits = []
    prev = None
    for row in feats.itertuples():
        f = row._asdict()
        if prev is not None and "vwap_dev" in prev:
            f["vwap_dev_prev"] = prev["vwap_dev"]
        prev = f
        for h in M.evaluate(symbol, f, ts=int(f.get("ts", 0))):
            hits.append(h)
    if not hits:
        return None
    import pandas as _pd

    df = _pd.DataFrame(hits)
    os.makedirs(out_root, exist_ok=True)
    out = f"{out_root}/{symbol}_{day}.parquet"
    df.to_parquet(out, index=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay situations over feature Parquet")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--range", required=True)
    args = ap.parse_args()

    start, end = args.range.split("..", 1)
    days = daterange(start, end)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    wrote = 0
    for sym in symbols:
        for day in days:
            out = replay(sym, day)
            if out:
                print(out)
                wrote += 1
    print(f"hits files written: {wrote}")


if __name__ == "__main__":
    main()
