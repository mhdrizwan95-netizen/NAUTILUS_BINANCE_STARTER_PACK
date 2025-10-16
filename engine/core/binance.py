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
        self._is_futures = getattr(settings, "is_futures", False)

    async def close(self) -> None:
        # Clients are created per-call; nothing persistent to close
        return None

    async def ticker_price(self, symbol: str) -> float:
        payload = {"symbol": symbol}
        # First attempt: standard public ticker endpoint
        try:
            path = "/fapi/v1/ticker/price" if self._is_futures else "/api/v3/ticker/price"
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                r = await client.get(path, params=payload)
            r.raise_for_status()
            data = r.json()
            price = float(data["price"])
            self._price_cache[symbol] = price
            return price
        except httpx.HTTPStatusError as e:
            # Testnet sometimes returns 418/429 on public endpoints. Try bookTicker
            if e.response is not None and e.response.status_code in (418, 429, 403):
                try:
                    fallback_path = "/fapi/v1/ticker/bookTicker" if self._is_futures else "/api/v3/ticker/bookTicker"
                    async with httpx.AsyncClient(
                        base_url=self._base,
                        timeout=self._settings.timeout,
                    ) as client:
                        r2 = await client.get(fallback_path, params=payload)
                    r2.raise_for_status()
                    d2 = r2.json()
                    # bookTicker gives best bid/ask; approximate mid
                    bid = float(d2.get("bidPrice", 0) or 0)
                    ask = float(d2.get("askPrice", 0) or 0)
                    px = (bid + ask) / 2.0 if bid and ask else (bid or ask)
                    if px:
                        self._price_cache[symbol] = px
                        return px
                except Exception:
                    # fallthrough to cache
                    pass
                # Last resort: cached price if available
                cached = self._price_cache.get(symbol)
                if cached:
                    return cached
            # Re-raise if not handled
            raise

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
                path = "/fapi/v1/exchangeInfo" if self._is_futures else "/api/v3/exchangeInfo"
                r = await client.get(path, params=params)
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
        base_params = {
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
        }
        # Retry a few times on throttling or ban codes which are common on demo/test clusters
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                path = "/fapi/v2/account" if self._is_futures else "/api/v3/account"
                r = await client.get(path, params=params)
                if r.status_code in (418, 429):
                    import logging, asyncio
                    logging.getLogger(__name__).warning(
                        "[BINANCE] /account returned %s (attempt %d) — backing off. body=%s",
                        r.status_code, attempt + 1, r.text,
                    )
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return {"balances": [], "positions": []}
            r.raise_for_status()
            return r.json()
        # Fallback (should never reach due to return above)
        return {"balances": [], "positions": []}

    async def my_trades_since(self, symbol: str, start_ms: int) -> list[dict[str, Any]]:
        """
        Fetch account trades for a symbol since a given timestamp (ms).
        Wraps GET /api/v3/myTrades and retries common testnet throttling codes.
        """
        settings = get_settings()
        base_params = {
            "symbol": symbol,
        }
        # Binance allows startTime/endTime filtering; we provide startTime only
        if start_ms and int(start_ms) > 0:
            base_params["startTime"] = int(start_ms)
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["recvWindow"] = settings.recv_window
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    path = "/fapi/v1/userTrades" if self._is_futures else "/api/v3/myTrades"
                    r = await client.get(path, params=params)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list):
                    return data
                # Defensive: sometimes returns object with 'rows'
                rows = data.get("rows") if isinstance(data, dict) else None
                return rows or []
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise

    async def submit_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
    ) -> dict[str, Any]:
        settings = get_settings()
        base_params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.8f}",
            "newOrderRespType": "FULL",
            "recvWindow": settings.recv_window,
        }
        # retry transient 418/429
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    path = "/fapi/v1/order" if self._is_futures else "/api/v3/order"
                    r = await client.post(path, data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise

    async def submit_market_quote(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quote: float,
    ) -> dict[str, Any]:
        # Futures API does not support quoteOrderQty for MARKET; emulate via qty
        if self._is_futures:
            px = await self.ticker_price(symbol)
            qty = max(quote / px, 0.0)
            # Round to step size if available
            try:
                filt = await self.exchange_filter(symbol)
                step = getattr(filt, "step_size", 0.000001) or 0.000001
                factor = 1.0 / float(step)
                qty = int(qty * factor) / factor
            except Exception:
                pass
            return await self.submit_market_order(symbol, side, qty)
        settings = get_settings()
        base_params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quoteOrderQty": f"{quote:.8f}",
            "newOrderRespType": "FULL",
            "recvWindow": settings.recv_window,
        }
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    r = await client.post("/api/v3/order", data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise

    async def submit_limit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
    ) -> dict[str, Any]:
        settings = get_settings()
        base_params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": time_in_force,
            "quantity": f"{quantity:.8f}",
            "price": f"{price:.8f}",
            "newOrderRespType": "FULL",
            "recvWindow": settings.recv_window,
        }
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    path = "/fapi/v1/order" if self._is_futures else "/api/v3/order"
                    r = await client.post(path, data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise

    def _sign(self, params: dict[str, Any]) -> str:
        secret = self._settings.api_secret.encode()
        query = urlencode(params)
        return hmac.new(secret, query.encode(), sha256).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)
