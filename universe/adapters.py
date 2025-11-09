from __future__ import annotations

import logging
import time
from typing import Any

from shared.binance_http import fetch_json

logger = logging.getLogger("universe.adapters")
_FETCH_ERRORS = (RuntimeError, ValueError)
_PARSE_ERRORS = (TypeError, ValueError)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


def fetch_exchange_info(quote: str = "USDT") -> list[str]:
    try:
        r = fetch_json("/api/v3/exchangeInfo")
    except _FETCH_ERRORS as exc:
        _log_suppressed("universe.exchange_info", exc)
        return []
    syms: list[str] = []
    for s in r.get("symbols", []):
        try:
            if (
                s.get("status") == "TRADING"
                and s.get("quoteAsset") == quote
                and s.get("isSpotTradingAllowed")
            ):
                syms.append(s["symbol"])
        except _PARSE_ERRORS:
            continue
    return syms


def fetch_top24h(symbols: list[str]) -> dict[str, Any]:
    try:
        r = fetch_json("/api/v3/ticker/24hr")
    except _FETCH_ERRORS as exc:
        _log_suppressed("universe.top24h", exc)
        return {}
    now = int(time.time())
    rank: dict[str, Any] = {}
    idx = {x.get("symbol"): x for x in r if isinstance(x, dict)}
    minutes = 24 * 60
    for s in symbols:
        x = idx.get(s)
        if not x:
            continue
        try:
            turnover = float(x.get("quoteVolume", 0.0))
            trades = int(x.get("count", 0))
        except _PARSE_ERRORS:
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
