# backtests/slippage_report.py
import pandas as pd


def slippage_summary(trades_csv: str) -> pd.DataFrame:
    t = pd.read_csv(trades_csv)
    if t.empty:
        return pd.DataFrame()
    # effective half-spread paid/received proxy
    t["signed_notional"] = t["qty"] * t["price"] * t["side"].map({"BUY": 1, "SELL": -1})
    # group by hour/day as needed
    grp = t.groupby(pd.to_datetime(t["ts_ns"], unit="ns").dt.floor("1H"))
    return grp["signed_notional"].sum().to_frame("signed_notional")
