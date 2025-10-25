from __future__ import annotations

import httpx
import time

BASE = "https://api.binance.com"


def fetch_exchange_info(quote: str = "USDT") -> list[str]:
    r = httpx.get(f"{BASE}/api/v3/exchangeInfo", timeout=10).json()
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
    r = httpx.get(f"{BASE}/api/v3/ticker/24hr", timeout=10).json()
    now = int(time.time())
    rank: dict = {}
    idx = {x.get("symbol"): x for x in r if isinstance(x, dict)}
    for s in symbols:
        x = idx.get(s)
        if not x:
            continue
        try:
            turnover = float(x.get("quoteVolume", 0.0))
            trades = int(x.get("count", 0))
        except Exception:
            turnover, trades = 0.0, 0
        rank[s] = {"turnover": turnover, "trades": trades, "ts": now}
    return rank
