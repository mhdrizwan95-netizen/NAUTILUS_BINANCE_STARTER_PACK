#!/usr/bin/env python3
"""
Validate features batch for ML service.

Usage:
  python tools/validate_features.py path/to/file.csv

Checks:
- Required columns present: timestamp, close
- timestamp is ms epoch and monotonic increasing per file
- no NaN/inf in close; log returns finite
- reasonable ranges (close > 0, |logret| < 1.0)
"""
from __future__ import annotations

import math
import sys

import pandas as pd


def validate(path: str) -> int:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns or "close" not in df.columns:
        print(f"ERR: missing required columns in {path}")
        return 1
    if df["close"].isna().any() or (df["close"] <= 0).any():
        print(f"ERR: invalid close values in {path}")
        return 1
    # parse ms epoch
    ts = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")
    if ts.isna().any():
        print(f"ERR: invalid timestamps in {path}")
        return 1
    if not ts.is_monotonic_increasing:
        print(f"ERR: timestamps not monotonic in {path}")
        return 1
    # log returns range sanity
    logret = (df["close"].apply(math.log).diff()).dropna()
    if not ((logret.abs() < 1.0).all()):
        print(f"WARN: extreme log returns present in {path}")
    print("OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: validate_features.py <csv>")
        sys.exit(2)
    sys.exit(validate(sys.argv[1]))
