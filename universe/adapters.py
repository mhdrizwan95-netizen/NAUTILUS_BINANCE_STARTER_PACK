from __future__ import annotations

import time

from shared.binance_http import fetch_json


def fetch_exchange_info(quote: str = "USDT") -> list[str]:
    r = fetch_json("/api/v3/exchangeInfo")
    syms: list[str] = []
    for s in r.get("symbols", []):
        try:
            if (
                s.get("status") == "TRADING"
                and s.get("quoteAsset") == quote
                and s.get("isSpotTradingAllowed")
            ):
                syms.append(s["symbol"])
        except Exception:
            continue
    return syms


def fetch_top24h(symbols: list[str]) -> dict:
    r = fetch_json("/api/v3/ticker/24hr")
    now = int(time.time())
    rank: dict = {}
    idx = {x.get("symbol"): x for x in r if isinstance(x, dict)}
    minutes = 24 * 60
    for s in symbols:
        x = idx.get(s)
        if not x:
            continue
        try:
            turnover = float(x.get("quoteVolume", 0.0))
            trades = int(x.get("count", 0))
        except Exception:
            turnover, trades = 0.0, 0
        notional_per_min = turnover / minutes if minutes else 0.0
        trade_rate = trades / minutes if minutes else 0.0
        rank[s] = {
            "turnover": turnover,
            "trades": trades,
            "notional_per_min": notional_per_min,
            "trade_rate": trade_rate,
            "ts": now,
        }
    return rank
