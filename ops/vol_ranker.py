"""
Ranks Binance symbols by recent volatility × liquidity.
Writes top symbols to data/top_symbols.txt for the ops executor.

Run once by default. With --loop, refreshes at a fixed interval.
Interval can be controlled via VOL_REFRESH_MIN (minutes).
"""

from __future__ import annotations

import os
import time
from typing import List, Optional
import argparse

import pandas as pd
from ops.net import create_client, request_with_retry_sync


BINANCE_API = os.getenv("BINANCE_API", "https://api.binance.com/api/v3/klines")
OUTPUT_FILE = os.getenv("VOL_TOP_FILE", "data/top_symbols.txt")
TOP_N = int(os.getenv("VOL_TOP_N", 20))
WINDOW_MIN = int(os.getenv("VOL_WINDOW_MIN", 60))  # last 60 min


def get_symbols() -> List[str]:
    try:
        with create_client() as client:
            r = request_with_retry_sync(
                client,
                "GET",
                "https://api.binance.com/api/v3/exchangeInfo",
                retries=2,
            )
            r.raise_for_status()
        data = r.json()
        # Focus on spot, quote USDT, trading enabled
        syms = [
            s["symbol"]
            for s in data.get("symbols", [])
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
        ]
        return syms
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


def get_klines(symbol: str, limit: int = 60) -> Optional[pd.DataFrame]:
    url = f"{BINANCE_API}?symbol={symbol}&interval=1m&limit={limit}"
    try:
        with create_client() as client:
            r = request_with_retry_sync(client, "GET", url, retries=2)
            r.raise_for_status()
        df = pd.DataFrame(
            r.json(),
            columns=[
                "t",
                "o",
                "h",
                "l",
                "c",
                "v",
                "ct",
                "qv",
                "n",
                "tb",
                "tq",
                "i",
            ],
        )
        if df.empty:
            return None
        df["c"] = df["c"].astype(float)
        df["v"] = df["v"].astype(float)
        return df
    except Exception:
        return None


def score_symbol(symbol: str) -> float:
    df = get_klines(symbol, limit=WINDOW_MIN)
    if df is None or df.empty:
        return 0.0
    try:
        ret = df["c"].pct_change().dropna()
        vol = ret.std()
        volscore = float(vol) * float(df["v"].mean())
        return float(volscore)
    except Exception:
        return 0.0


def run_once() -> int:
    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    symbols = get_symbols()
    scores = []
    for s in symbols:
        sc = score_symbol(s)
        if sc > 0:
            scores.append((s, sc))
        # Polite to the API: ~20 rps cap overall
        time.sleep(0.05)
    top = sorted(scores, key=lambda x: x[1], reverse=True)[:TOP_N]
    # Atomic write to avoid partial reads
    tmp_path = OUTPUT_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        for s, _ in top:
            f.write(f"{s}\n")
    os.replace(tmp_path, OUTPUT_FILE)
    print(f"[vol_ranker] wrote top {len(top)} symbols to {OUTPUT_FILE}")
    return len(top)


def main() -> None:
    global TOP_N, OUTPUT_FILE
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run refresh loop")
    parser.add_argument(
        "--interval-sec", type=int, default=3600, help="Refresh interval in seconds"
    )
    parser.add_argument(
        "--top-n", type=int, default=TOP_N, help="Number of top symbols to select"
    )
    parser.add_argument("--out", default=OUTPUT_FILE, help="Output file path")
    args = parser.parse_args()

    TOP_N = args.top_n
    OUTPUT_FILE = args.out

    if not args.loop:
        run_once()
        return

    refresh_sec = max(60, args.interval_sec)
    print(f"[vol_ranker] starting loop, interval={refresh_sec}s -> {OUTPUT_FILE}")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[vol_ranker] error during refresh: {e}")
        time.sleep(refresh_sec)


if __name__ == "__main__":
    main()
