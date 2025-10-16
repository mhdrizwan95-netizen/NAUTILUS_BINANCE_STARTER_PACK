from __future__ import annotations

import asyncio
import hmac
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from engine.config import get_settings


@dataclass(frozen=True)
class SymbolFilter:
    symbol: str
    step_size: float
    min_qty: float
    min_notional: float
    max_notional: float
    tick_size: float = 0.0


class BinanceREST:
    """Minimal async REST client for Binance spot endpoints."""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._base = settings.base_url.rstrip("/")
        self._symbol_filters: dict[str, SymbolFilter] = {}
        self._price_cache: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        # Clients are created per-call; nothing persistent to close
        return None

    async def ticker_price(self, symbol: str) -> float:
        payload = {"symbol": symbol}
        async with httpx.AsyncClient(
            base_url=self._base,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            r = await client.get("/api/v3/ticker/price", params=payload)
        r.raise_for_status()
        data = r.json()
        price = float(data["price"])
        self._price_cache[symbol] = price
        return price

    async def exchange_filter(self, symbol: str) -> SymbolFilter:
        async with self._lock:
            cached = self._symbol_filters.get(symbol)
            if cached:
                return cached
            params = {"symbol": symbol}
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                r = await client.get("/api/v3/exchangeInfo", params=params)
            r.raise_for_status()
            info = r.json()
            symbols = info.get("symbols", [])
            if not symbols:
                raise RuntimeError(f"Symbol {symbol} not found in exchangeInfo response.")
            filters = symbols[0].get("filters", [])
            step_size = 0.000001
            min_qty = 0.0
            min_notional = 0.0
            max_notional = float("inf")
            tick_size = 0.0
            for f in filters:
                ftype = f.get("filterType")
                if ftype == "LOT_SIZE":
                    step_size = float(f.get("stepSize", 0.000001))
                    min_qty = float(f.get("minQty", 0.0))
                elif ftype == "NOTIONAL":
                    min_notional = float(f.get("minNotional", 0.0))
                    max_notional = float(f.get("maxNotional", float("inf")))
                elif ftype == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", 0.0))
            filt = SymbolFilter(symbol, step_size, min_qty, min_notional, max_notional, tick_size)
            self._symbol_filters[symbol] = filt
            return filt

    async def account_snapshot(self) -> dict[str, Any]:
        settings = get_settings()
        params = {
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
        }
        params["signature"] = self._sign(params)
        async with httpx.AsyncClient(
            base_url=self._base,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            r = await client.get("/api/v3/account", params=params)
        r.raise_for_status()
        return r.json()

    async def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
    ) -> dict[str, Any]:
        settings = get_settings()
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.8f}",
            "newOrderRespType": "FULL",
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
        }
        params["signature"] = self._sign(params)
        async with httpx.AsyncClient(
            base_url=self._base,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            r = await client.post("/api/v3/order", data=params)
        # For MARKET quote orders we must use POST /api/v3/order/test? but test? We'll rely on real /order.
        r.raise_for_status()
        return r.json()

    async def submit_market_quote(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quote: float,
    ) -> dict[str, Any]:
        settings = get_settings()
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quoteOrderQty": f"{quote:.8f}",
            "newOrderRespType": "FULL",
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
        }
        params["signature"] = self._sign(params)
        async with httpx.AsyncClient(
            base_url=self._base,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            r = await client.post("/api/v3/order", data=params)
        r.raise_for_status()
        return r.json()

    async def submit_limit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
    ) -> dict[str, Any]:
        settings = get_settings()
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": time_in_force,
            "quantity": f"{quantity:.8f}",
            "price": f"{price:.8f}",
            "newOrderRespType": "FULL",
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
        }
        params["signature"] = self._sign(params)
        async with httpx.AsyncClient(
            base_url=self._base,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            r = await client.post("/api/v3/order", data=params)
        r.raise_for_status()
        return r.json()

    def _sign(self, params: dict[str, Any]) -> str:
        secret = self._settings.api_secret.encode()
        query = urlencode(params)
        return hmac.new(secret, query.encode(), sha256).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)
