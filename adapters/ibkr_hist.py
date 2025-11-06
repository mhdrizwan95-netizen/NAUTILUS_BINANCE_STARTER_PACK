from __future__ import annotations

"""
IBKR historical bars (1-minute) via ib_insync.

Writes Parquet under:
  data/raw/ibkr/equities/1m/<SYMBOL>/<YYYY>/<YYYY-MM-DD>.parquet

Requires a running TWS or IB Gateway and ib_insync installed.
"""

import os

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def fetch_1m(
    ticker: str = "AAPL", endDateTime: str = "", durationStr: str = "2 W"
) -> pd.DataFrame:
    try:
        from ib_insync import IB, Stock, util
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("ib_insync not installed: pip install ib_insync") from exc

    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497"))
    client_id = int(os.getenv("IBKR_HIST_CLIENT_ID", "19"))

    ib = IB()
    ib.connect(host, port, clientId=client_id)
    contract = Stock(ticker, "SMART", "USD")
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=endDateTime,
        durationStr=durationStr,
        barSizeSetting="1 min",
        whatToShow="TRADES",
        useRTH=False,
        formatDate=1,
    )
    df = util.df(bars)  # date, open, high, low, close, volume, barCount, WAP
    df["ts"] = pd.to_datetime(df["date"]).astype("int64") // 10**9
    df.rename(columns={"WAP": "vwap", "barCount": "trades"}, inplace=True)
    df = df[["ts", "open", "high", "low", "close", "volume", "trades"]]
    return df


def save_day(
    symbol: str,
    yyyy_mm_dd: str,
    df: pd.DataFrame,
    root: str = "data/raw/ibkr/equities/1m",
) -> str:
    year = yyyy_mm_dd[:4]
    path = f"{root}/{symbol}/{year}/{yyyy_mm_dd}.parquet"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path)
    return path


__all__ = ["fetch_1m", "save_day"]


if __name__ == "__main__":
    import argparse
    import datetime as dt

    ap = argparse.ArgumentParser(
        description="Download IBKR 1m bars and save Parquet by day"
    )
    ap.add_argument(
        "--symbols", required=True, help="Comma-separated tickers, e.g. AAPL,NVDA"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--day", help="Single day YYYY-MM-DD (downloads a window covering that day)"
    )
    g.add_argument(
        "--duration",
        help="IBKR durationStr, e.g. '2 W' (mutually exclusive with --day)",
    )
    args = ap.parse_args()

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.day:
        # IBKR requires duration; request 1 D ending the next day
        end = dt.datetime.fromisoformat(args.day) + dt.timedelta(days=1)
        end_str = end.strftime("%Y%m%d %H:%M:%S")
        duration = "1 D"
        for sym in syms:
            df = fetch_1m(sym, endDateTime=end_str, durationStr=duration)
            save_day(sym, args.day, df)
            print(f"saved {sym} {args.day}")
    else:
        for sym in syms:
            df = fetch_1m(sym, endDateTime="", durationStr=args.duration)
            print(f"downloaded {sym} rows={len(df)}")
