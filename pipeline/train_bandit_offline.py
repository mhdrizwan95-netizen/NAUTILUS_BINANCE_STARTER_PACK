from __future__ import annotations

import argparse
import glob
import json
import math
import os
from typing import Dict

import pandas as pd


def train(
    pattern: str = "data/outcomes/*.parquet",
    c: float = 1.0,
    situations_path: str = "config/situations.json",
) -> Dict[str, float]:
    paths = sorted(glob.glob(pattern))
    if not paths:
        return {}
    df = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    if df.empty:
        return {}
    g = df.groupby("situation")["pnl_usd"]
    stats = g.agg(["count", "mean", "var"]).reset_index().fillna(0.0)
    N = max(float(stats["count"].sum()), 1.0)
    stats["ucb"] = stats.apply(
        lambda r: float(r["mean"])
        + float(c) * math.sqrt(max(math.log(N), 0.0) / max(float(r["count"]), 1.0)),
        axis=1,
    )
    lo, hi = float(stats["ucb"].min()), float(stats["ucb"].max())
    span = (hi - lo) or 1.0
    stats["priority"] = stats.apply(lambda r: (float(r["ucb"]) - lo) / span, axis=1)

    # Update situations.json in place
    sits = json.loads(open(situations_path).read())
    idx = {s["name"]: i for i, s in enumerate(sits)}
    out: Dict[str, float] = {}
    for _, r in stats.iterrows():
        name = str(r["situation"])
        pr = float(r["priority"])
        if name in idx:
            sits[idx[name]]["priority"] = pr
            out[name] = pr
    tmp = situations_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sits, f, indent=2)
    os.replace(tmp, situations_path)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Train UCB priorities from offline outcomes")
    ap.add_argument("--pattern", default="data/outcomes/*.parquet")
    ap.add_argument("--c", type=float, default=1.0)
    args = ap.parse_args()
    res = train(args.pattern, args.c)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
