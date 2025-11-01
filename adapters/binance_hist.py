from __future__ import annotations

"""
Historical data downloader for Binance spot klines.

Writes Parquet partitioned by symbol/year/day under:
  data/raw/binance/spot/1m/<SYMBOL>/<YYYY>/<YYYY-MM-DD>.parquet

CLI is intentionally omitted; use from Makefile or notebooks.
"""

import os
import time
from datetime import datetime, timezone
from typing import List

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BASE = os.getenv("BINANCE_HIST_BASE", "https://api.binance.com")


def fetch_klines(
    symbol: str, start_ms: int, end_ms: int, interval: str = "1m"
) -> pd.DataFrame:
    """Fetch klines for [start_ms, end_ms) inclusive window.

    Returns a DataFrame with columns:
      ts, open, high, low, close, volume, quote_volume, trades
    """
    out: List[list] = []
    start = int(start_ms)
    end = int(end_ms)
    with httpx.Client(timeout=20.0) as client:
        while start < end:
            r = client.get(
                f"{BASE}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": start,
                    "endTime": end,
                    "limit": 1000,
                },
            )
            r.raise_for_status()
            kl = r.json()
            if not kl:
                break
            out.extend(kl)
            # next request starts after the last returned bar
            start = int(kl[-1][0]) + 60_000
            time.sleep(0.2)  # light throttling

    if not out:
        return pd.DataFrame(
            columns=[
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "quote_volume",
                "trades",
            ]
        )

    df = pd.DataFrame(
        out,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "num_trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ],
    )
    df = df.assign(
        ts=(df["open_time"] // 1000).astype("int64"),
        open=df["open"].astype(float),
        high=df["high"].astype(float),
        low=df["low"].astype(float),
        close=df["close"].astype(float),
        volume=df["volume"].astype(float),
        quote_volume=df["quote_asset_volume"].astype(float),
        trades=df["num_trades"].astype(int),
    )[
        [
            "ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades",
        ]
    ]
    return df


def save_day(
    symbol: str,
    yyyy_mm_dd: str,
    df: pd.DataFrame,
    root: str = "data/raw/binance/spot/1m",
) -> str:
    """Persist a single day file to Parquet under the partitioned hierarchy."""
    year = yyyy_mm_dd[:4]
    path = f"{root}/{symbol}/{year}/{yyyy_mm_dd}.parquet"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path)
    return path


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


__all__ = ["fetch_klines", "save_day", "_ms"]


if __name__ == "__main__":
    import argparse
    import datetime as dt

    ap = argparse.ArgumentParser(
        description="Download Binance klines and save Parquet by day"
    )
    ap.add_argument(
        "--symbols", required=True, help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--day", help="Single day YYYY-MM-DD")
    g.add_argument("--range", help="Range YYYY-MM-DD..YYYY-MM-DD inclusive")
    args = ap.parse_args()

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    days: list[str] = []
    if args.day:
        days = [args.day]
    else:
        s, e = args.range.split("..", 1)
        ds = dt.date.fromisoformat(s)
        de = dt.date.fromisoformat(e)
        cur = ds
        while cur <= de:
            days.append(cur.isoformat())
            cur += dt.timedelta(days=1)

    for d in days:
        start = dt.datetime.fromisoformat(d)
        end = start + dt.timedelta(days=1)
        start_ms = _ms(start)
        end_ms = _ms(end)
        for sym in syms:
            df = fetch_klines(sym, start_ms, end_ms, interval="1m")
            path = save_day(sym, d, df)
            print(path, flush=True)
