from __future__ import annotations

import asyncio
import logging
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
    max_notional: float | None = None
    tick_size: float = 0.0


class BinanceREST:
    """Minimal async REST client for Binance spot endpoints."""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        # Use futures base or spot base depending on mode
        base = getattr(settings, "api_base", None)
        if not base:
            base = settings.base_url  # fallback
        self._base = base.rstrip("/")
        self._symbol_filters: dict[str, SymbolFilter] = {}
        self._price_cache: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._is_futures = getattr(settings, "is_futures", False)
        self._logger = logging.getLogger("engine.binance.rest")

    # ---- Debug helpers ----
    def _mask_payload(self, payload: dict | None) -> dict | None:
        if not payload:
            return payload
        try:
            masked = dict(payload)
            if "signature" in masked:
                masked["signature"] = "<redacted>"
            return masked
        except Exception:
            return payload

    def _log_request(self, method: str, path: str, *, params: dict | None = None, data: dict | None = None) -> None:
        url = f"{self._base}{path}"
        # Log URL at INFO for visibility; payloads at DEBUG
        try:
            self._logger.info("[BINANCE] %s %s", method.upper(), url)
            m_params = self._mask_payload(params)
            m_data = self._mask_payload(data)
            self._logger.debug("[BINANCE] payload params=%s data=%s", m_params, m_data)
        except Exception:
            # Never let logging break request flow
            pass

    async def close(self) -> None:
        # Clients are created per-call; nothing persistent to close
        return None

    async def ticker_price(self, symbol: str) -> float:
        payload = {"symbol": symbol}
        # First attempt: use mark price for futures (official UPNL basis), last price for spot
        try:
            if self._is_futures:
                path = "/fapi/v1/premiumIndex"
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("GET", path, params=payload)
                    r = await client.get(path, params=payload)
                r.raise_for_status()
                data = r.json()
                price = float(data["markPrice"])
            else:
                path = "/api/v3/ticker/price"
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("GET", path, params=payload)
                    r = await client.get(path, params=payload)
                r.raise_for_status()
                data = r.json()
                price = float(data["price"])
            self._price_cache[symbol] = price
            return price
        except Exception:
            # Fallback: try the opposite endpoint or return cached value
            try:
                # Try opposite endpoint as fallback
                fallback_path = "/api/v3/ticker/price" if self._is_futures else "/fapi/v1/premiumIndex"
                async with httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("GET", fallback_path, params=payload)
                    r = await client.get(fallback_path, params=payload)
                r.raise_for_status()
                data = r.json()
                price = float(data.get("price", data.get("markPrice", 0)))
                self._price_cache[symbol] = price
                return price
            except Exception:
                # Final fallback: return cached value or raise
                return self._price_cache.get(symbol, 0.0) or 0.0

    async def bulk_premium_index(self) -> dict[str, float]:
        """Fetch mark prices for all futures symbols."""
        try:
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                self._log_request("GET", "/fapi/v1/premiumIndex")
                r = await client.get("/fapi/v1/premiumIndex")
            r.raise_for_status()
            data = r.json()
            price_map = {}
            for item in data:
                symbol = item.get("symbol", "")
                mark_price = float(item.get("markPrice", 0))
                if symbol and mark_price > 0:
                    price_map[symbol] = mark_price
            return price_map
        except Exception:
            return {}

    async def position_risk(self) -> list[dict[str, Any]]:
        """Fetch venue positionRisk data (basis, PnL, amt)."""
        settings = self._settings
        base_params = {"recvWindow": settings.recv_window}
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
                    path = "/fapi/v2/positionRisk" if self._is_futures else "/api/v3/account"
                    self._log_request("GET", path, params=params)
                    r = await client.get(path, params=params)
                r.raise_for_status()
                data = r.json()
                return data if isinstance(data, list) else (data.get("positions", []) if isinstance(data, dict) else [])
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                return []
        return []

    async def hedge_mode(self) -> bool:
        """Check if dual Futures hedge mode is enabled."""
        settings = self._settings
        base_params = {
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
            "signature": self._sign({
                "timestamp": str(_now_ms()),
                "recvWindow": str(settings.recv_window),
            }),
        }
        for attempt in range(3):
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                self._log_request("GET", "/fapi/v1/positionSide/dual", params=base_params)
                r = await client.get("/fapi/v1/positionSide/dual", params=base_params)
            r.raise_for_status()
            data = r.json()
            is_hedge = bool(data.get("dualSidePosition", False))
            return is_hedge
        return False

    async def account(self) -> dict[str, Any]:
        """Fetch account totals for USDT futures."""
        settings = self._settings
        base_params = {
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
        }
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                path = "/fapi/v2/account"
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            r.raise_for_status()
            return r.json()
        return {}


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
                self._log_request("GET", path, params=params)
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
                if ftype in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                    # Futures can return LOT_SIZE; some variants report MARKET_LOT_SIZE
                    step_size = float(f.get("stepSize", step_size or 0.000001))
                    min_qty = float(f.get("minQty", min_qty or 0.0))
                elif ftype in ("NOTIONAL", "MIN_NOTIONAL"):
                    # Support both names; MIN_NOTIONAL appears on some venues/contracts
                    mn = f.get("minNotional")
                    mx = f.get("maxNotional", None)
                    try:
                        min_notional = float(mn) if mn is not None else min_notional
                    except Exception:
                        # If venue sends something strange, keep previous/default
                        pass
                    try:
                        max_notional = float(mx) if mx is not None else max_notional
                    except Exception:
                        pass
                elif ftype == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", tick_size or 0.0))
            # Sanitize numeric outputs for JSON + downstream math
            # step_size must be positive; default to 1e-6 if absent/invalid
            if not isinstance(step_size, (int, float)) or step_size <= 0:
                step_size = 0.000001
            if not isinstance(min_qty, (int, float)) or min_qty < 0:
                min_qty = 0.0
            # Infinity/<=0 max_notional -> None (meaning "no cap")
            if not isinstance(max_notional, (int, float)) or str(max_notional).lower() in ("inf", "+inf") or (isinstance(max_notional, (int, float)) and max_notional <= 0):
                safe_max_notional = None
            else:
                safe_max_notional = float(max_notional)
            filt = SymbolFilter(symbol, step_size, min_qty, min_notional, safe_max_notional, tick_size)
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
                self._log_request("GET", path, params=params)
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
                    self._log_request("GET", path, params=params)
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
                    self._log_request("POST", path, data=params)
                    r = await client.post(path, data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                body = ""
                status = 0
                try:
                    status = e.response.status_code
                    body = e.response.text
                except Exception:
                    pass
                if status in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Binance error (submit_market_order) status={status} body={body}") from e

    async def submit_market_quote(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quote: float,
    ) -> dict[str, Any]:
        if self._is_futures:
            # Futures API does not support quoteOrderQty for MARKET; emulate via qty
            px = await self.ticker_price(symbol)
            # Pull filters (step size & min qty)
            try:
                filt = await self.exchange_filter(symbol)
                step = getattr(filt, "step_size", 0.000001) or 0.000001
                min_qty = getattr(filt, "min_qty", 0.0) or 0.0
            except Exception:
                # Fallbacks if exchangeInfo fails
                step = 0.000001
                min_qty = 0.0
                filt = None
            # Convert quote to base quantity and round DOWN to step
            qty_raw = max(quote / px, 0.0)
            factor = 1.0 / float(step)
            qty = int(qty_raw * factor) / factor
            # Pre-trade guard: reject too-small quote before submission
            min_quote_req = (min_qty or step) * px
            if quote < min_quote_req:
                raise RuntimeError(
                    f"quote too small: provided={quote:.4f} < required≈{min_quote_req:.4f} USDT "
                    f"(step={step}, min_qty={min_qty}, px≈{px:.2f})"
                )
            # Guardrails: reject if rounding makes qty invalid
            if qty <= 0 or (min_qty and qty < min_qty):
                needed = (min_qty or step) * px
                raise RuntimeError(
                    f"quote too small for futures: quote={quote:.8f} {symbol}, "
                    f"px≈{px:.8f}, step={step}, min_qty={min_qty}. "
                    f"Required quote≈{needed:.4f} USDT"
                )
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
                    path = "/api/v3/order"
                    self._log_request("POST", path, data=params)
                    r = await client.post(path, data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                body = ""
                status = 0
                try:
                    status = e.response.status_code
                    body = e.response.text
                except Exception:
                    pass
                if status in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Binance error (submit_market_quote) status={status} body={body}") from e

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
                    self._log_request("POST", path, data=params)
                    r = await client.post(path, data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                body = ""
                status = 0
                try:
                    status = e.response.status_code
                    body = e.response.text
                except Exception:
                    pass
                if status in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Binance error (submit_limit_order) status={status} body={body}") from e

    def _sign(self, params: dict[str, Any]) -> str:
        secret = self._settings.api_secret.encode()
        query = urlencode(params)
        return hmac.new(secret, query.encode(), sha256).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)
