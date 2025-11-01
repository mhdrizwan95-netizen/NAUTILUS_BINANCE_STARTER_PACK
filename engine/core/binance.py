from __future__ import annotations

import asyncio
import logging
import hmac
import math
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, Optional, Tuple
from urllib.parse import urlencode

import httpx

from engine.config import get_settings


def _truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SymbolFilter:
    symbol: str
    step_size: float
    min_qty: float
    min_notional: float
    max_notional: float | None = None
    tick_size: float = 0.0


TRANSFER_TYPES: set[str] = {
    "FUNDING_MAIN",
    "MAIN_FUNDING",
    "MAIN_UMFUTURE",
    "UMFUTURE_MAIN",
    "FUNDING_UMFUTURE",
    "UMFUTURE_FUNDING",
}


def _margin_isolated_default() -> bool:
    value = os.getenv("BINANCE_MARGIN_ISOLATED")
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BinanceREST:
    """Minimal async REST client for Binance spot/futures/margin endpoints."""

    def __init__(
        self, *, market: Literal["spot", "futures", "margin"] | None = None
    ) -> None:
        settings = get_settings()
        self._settings = settings
        # Capture base URLs for each market upfront (fall back to primary base_url)
        spot_base = getattr(settings, "spot_base", "") or getattr(
            settings, "base_url", ""
        )
        if not spot_base:
            spot_base = "https://api.binance.com"
        futures_base = getattr(settings, "futures_base", "") or spot_base
        self._spot_base = spot_base.rstrip("/")
        self._futures_base = futures_base.rstrip("/")
        self._margin_base = self._spot_base  # Margin orders share the spot REST host
        options_base = getattr(settings, "options_base", "")
        self._options_base = options_base.rstrip("/") if options_base else ""

        available = {"spot"}
        if self._futures_base:
            available.add("futures")
        if _truthy(os.getenv("BINANCE_MARGIN_ENABLED")):
            available.add("margin")
        if getattr(settings, "options_enabled", False) and self._options_base:
            available.add("options")
        self._available_markets = available

        default_market = (
            market or ("futures" if getattr(settings, "is_futures", False) else "spot")
        ).lower()
        if default_market not in self._available_markets:
            default_market = "spot"
        self._default_market = default_market

        # Preserve legacy attributes for backwards compatibility
        if default_market == "options" and self._options_base:
            self._base = self._options_base
        else:
            self._base = (
                self._futures_base if default_market == "futures" else self._spot_base
            )
        self._is_futures = default_market == "futures"

        self._symbol_filters: dict[tuple[str, str], SymbolFilter] = {}
        self._price_cache: dict[tuple[str, str], float] = {}
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger("engine.binance.rest")

    def _clean_symbol(self, symbol: str) -> str:
        return symbol.split(".")[0].upper()

    def available_markets(self) -> tuple[str, ...]:
        return tuple(sorted(self._available_markets))

    def _resolve_market(self, market: Optional[str]) -> Tuple[str, str, bool]:
        mk = (market or self._default_market or "spot").lower()
        if mk not in self._available_markets:
            # Prefer default if still valid, otherwise first available
            fallback = (
                self._default_market
                if self._default_market in self._available_markets
                else next(iter(self._available_markets))
            )
            mk = fallback
        if mk == "futures":
            return mk, self._futures_base, True
        if mk == "margin":
            return mk, self._margin_base, False
        if mk == "options":
            base = self._options_base or self._spot_base
            return mk, base, False
        return "spot", self._spot_base, False

    def _default_resp_type(self, market: Optional[str] = None) -> str:
        market_key, _, is_futures = self._resolve_market(market)
        if market_key == "options":
            return "FULL"
        return "RESULT" if is_futures else "FULL"

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

    def _log_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
    ) -> None:
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

    def _sign(self, params: dict[str, Any]) -> str:
        """
        Return HMAC-SHA256 signature for Binance signed endpoints.

        Binance expects the query string (without URL encoding) signed with the API
        secret. We guard against missing credentials so dry-run/test deployments can
        still exercise the REST client without crashing the engine; in that case an
        empty signature is returned and upstream calls will fail fast with a clear
        error from Binance.
        """
        secret = getattr(self._settings, "api_secret", "") or ""
        if not secret:
            self._logger.debug(
                "Signing request without API secret (dry-run/test configuration)"
            )
            return ""
        query = urlencode(params, doseq=True)
        return hmac.new(secret.encode(), query.encode(), sha256).hexdigest()

    async def close(self) -> None:
        # Clients are created per-call; nothing persistent to close
        return None

    async def ticker_price(self, symbol: str, *, market: Optional[str] = None) -> float:
        clean = self._clean_symbol(symbol)
        market_key, base_url, is_futures = self._resolve_market(market)
        payload = {"symbol": clean}
        # First attempt: use mark price for futures/options, last price for spot
        try:
            if market_key == "options":
                path = "/vapi/v1/mark"
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("GET", path, params=payload)
                    r = await client.get(path, params=payload)
                r.raise_for_status()
                raw = r.json()
                if isinstance(raw, list):
                    price = 0.0
                    for item in raw:
                        if str(item.get("symbol", "")).upper() == clean:
                            price = float(
                                item.get("markPrice") or item.get("price") or 0.0
                            )
                            break
                elif isinstance(raw, dict):
                    price = float(raw.get("markPrice") or raw.get("price") or 0.0)
                else:
                    price = 0.0
            elif is_futures:
                path = "/fapi/v1/premiumIndex"
                async with httpx.AsyncClient(
                    base_url=base_url,
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
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("GET", path, params=payload)
                    r = await client.get(path, params=payload)
                r.raise_for_status()
                data = r.json()
                price = float(data["price"])
            self._price_cache[(market_key, clean)] = price
            return price
        except Exception:
            # Fallback: try the opposite endpoint or return cached value
            try:
                # Try opposite endpoint as fallback
                if market_key == "options":
                    fallback_path = "/api/v3/ticker/price"
                    fallback_base = self._spot_base
                elif is_futures:
                    fallback_path = "/api/v3/ticker/price"
                    fallback_base = self._spot_base
                else:
                    fallback_path = "/fapi/v1/premiumIndex"
                    fallback_base = self._futures_base
                async with httpx.AsyncClient(
                    base_url=fallback_base,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("GET", fallback_path, params=payload)
                    r = await client.get(fallback_path, params=payload)
                r.raise_for_status()
                data = r.json()
                price = float(data.get("price", data.get("markPrice", 0)))
                self._price_cache[(market_key, clean)] = price
                return price
            except Exception:
                # Final fallback: return cached value or raise
                return self._price_cache.get((market_key, clean), 0.0) or 0.0

    async def bulk_premium_index(
        self, *, market: Optional[str] = None
    ) -> dict[str, dict[str, Any]]:
        """Fetch mark prices for all futures symbols."""
        market_key, base_url, is_futures = self._resolve_market(market)
        if not is_futures:
            return {}
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
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
                if not symbol:
                    continue
                payload = {
                    "markPrice": float(item.get("markPrice", 0.0) or 0.0),
                    "indexPrice": float(item.get("indexPrice", 0.0) or 0.0),
                    "lastFundingRate": item.get("lastFundingRate"),
                    "estimatedSettlePrice": float(
                        item.get("estimatedSettlePrice", 0.0) or 0.0
                    ),
                    "estimatedRate": item.get("estimatedRate"),
                    "nextFundingTime": item.get("nextFundingTime"),
                    "time": item.get("time"),
                }
                price_map[str(symbol).upper()] = payload
            return price_map
        except Exception:
            return {}

    async def position_risk(
        self, *, market: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch venue positionRisk data (basis, PnL, amt)."""
        market_key, base_url, is_futures = self._resolve_market(market)
        if not is_futures:
            return []
        settings = self._settings
        base_params = {"recvWindow": settings.recv_window}
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    path = "/fapi/v2/positionRisk" if is_futures else "/api/v3/account"
                    self._log_request("GET", path, params=params)
                    r = await client.get(path, params=params)
                r.raise_for_status()
                data = r.json()
                return (
                    data
                    if isinstance(data, list)
                    else (data.get("positions", []) if isinstance(data, dict) else [])
                )
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

    async def hedge_mode(self, *, market: Optional[str] = None) -> bool:
        """Check if dual Futures hedge mode is enabled."""
        market_key, base_url, is_futures = self._resolve_market(market)
        if not is_futures:
            return False
        settings = self._settings
        base_params = {
            "timestamp": _now_ms(),
            "recvWindow": settings.recv_window,
            "signature": self._sign(
                {
                    "timestamp": str(_now_ms()),
                    "recvWindow": str(settings.recv_window),
                }
            ),
        }
        for attempt in range(3):
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                self._log_request(
                    "GET", "/fapi/v1/positionSide/dual", params=base_params
                )
                r = await client.get("/fapi/v1/positionSide/dual", params=base_params)
            r.raise_for_status()
            data = r.json()
            is_hedge = bool(data.get("dualSidePosition", False))
            return is_hedge
        return False

    async def account(self, *, market: Optional[str] = None) -> dict[str, Any]:
        """Fetch account totals for USDT futures."""
        market_key, base_url, is_futures = self._resolve_market(market)
        if not is_futures:
            return {}
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
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                path = "/fapi/v2/account"
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            r.raise_for_status()
            return r.json()
        return {}

    async def futures_change_leverage(
        self, symbol: str, leverage: int
    ) -> dict[str, Any]:
        """Set leverage for a futures symbol."""
        market_key, base_url, is_futures = self._resolve_market("futures")
        if not is_futures:
            raise RuntimeError("Futures market not available for leverage change")
        clean_symbol = self._clean_symbol(symbol)
        settings = self._settings
        base_params = {
            "symbol": clean_symbol,
            "leverage": int(leverage),
            "recvWindow": settings.recv_window,
        }
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    path = "/fapi/v1/leverage"
                    self._log_request("POST", path, data=params)
                    r = await client.post(path, data=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response is not None else 0
                if status in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                body = ""
                try:
                    body = e.response.text  # type: ignore[assignment]
                except Exception:
                    body = ""
                raise RuntimeError(
                    f"Binance leverage change failed status={status} body={body}"
                ) from e
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                raise
        return {}

    async def order_status(
        self,
        symbol: str,
        *,
        order_id: int | str | None = None,
        client_order_id: str | None = None,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Fetch order status (GET /fapi/v1/order or /api/v3/order).

        Binance returns executedQty=0 for MARKET orders on placement; this helper
        lets callers immediately re-query to obtain the final qty/price.
        """
        if not order_id and not client_order_id:
            raise ValueError("order_status requires order_id or client_order_id")
        settings = get_settings()
        base_params: dict[str, Any] = {
            "symbol": self._clean_symbol(symbol),
            "recvWindow": settings.recv_window,
        }
        if order_id:
            base_params["orderId"] = int(order_id)
        if client_order_id:
            base_params["origClientOrderId"] = client_order_id
        market_key, base_url, is_futures = self._resolve_market(market)
        if market_key == "margin" and _margin_isolated_default():
            base_params["isIsolated"] = "TRUE"
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                if is_futures:
                    path = "/fapi/v1/order"
                elif market_key == "margin":
                    path = "/sapi/v1/margin/order"
                elif market_key == "options":
                    path = "/vapi/v1/order"
                else:
                    path = "/api/v3/order"
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            try:
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
                raise RuntimeError(
                    f"Binance error (order_status) status={status} body={body}"
                ) from e
        return {}

    async def exchange_filter(
        self, symbol: str, *, market: Optional[str] = None
    ) -> SymbolFilter:
        async with self._lock:
            clean = self._clean_symbol(symbol)
            market_key, base_url, is_futures = self._resolve_market(market)
            cache_key = (market_key, clean)
            cached = self._symbol_filters.get(cache_key)
            if cached:
                return cached
            if market_key == "options":
                filt = SymbolFilter(
                    symbol=clean,
                    step_size=1.0,
                    min_qty=1.0,
                    min_notional=0.0,
                    max_notional=None,
                    tick_size=0.0,
                )
                self._symbol_filters[cache_key] = filt
                return filt

            params = {"symbol": clean}
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                path = "/fapi/v1/exchangeInfo" if is_futures else "/api/v3/exchangeInfo"
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            r.raise_for_status()
            info = r.json()
            symbols = info.get("symbols", [])
            if not symbols:
                raise RuntimeError(
                    f"Symbol {symbol} not found in exchangeInfo response."
                )
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
            if (
                not isinstance(max_notional, (int, float))
                or str(max_notional).lower() in ("inf", "+inf")
                or (isinstance(max_notional, (int, float)) and max_notional <= 0)
            ):
                safe_max_notional = None
            else:
                safe_max_notional = float(max_notional)
            filt = SymbolFilter(
                clean, step_size, min_qty, min_notional, safe_max_notional, tick_size
            )
            self._symbol_filters[cache_key] = filt
            return filt

    async def account_snapshot(self, *, market: Optional[str] = None) -> dict[str, Any]:
        market_key, base_url, is_futures = self._resolve_market(market)
        if market_key == "margin":
            return await self.margin_account()
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
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                path = "/fapi/v2/account" if is_futures else "/api/v3/account"
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
                if r.status_code in (418, 429):
                    import logging, asyncio

                    logging.getLogger(__name__).warning(
                        "[BINANCE] /account returned %s (attempt %d) — backing off. body=%s",
                        r.status_code,
                        attempt + 1,
                        r.text,
                    )
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return {"balances": [], "positions": []}
            r.raise_for_status()
            return r.json()
        # Fallback (should never reach due to return above)
        return {"balances": [], "positions": []}

    async def margin_account(self) -> dict[str, Any]:
        """Fetch cross-margin account summary if available (spot SAPI).

        Returns a dict that may include a field `marginLevel`.
        Best-effort: returns {} if endpoint not available or in futures mode.
        """
        try:
            settings = get_settings()
            params = {
                "timestamp": _now_ms(),
                "recvWindow": settings.recv_window,
            }
            params["signature"] = self._sign(params)
            _, base_url, _ = self._resolve_market("margin")
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                path = "/sapi/v1/margin/account"
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    async def margin_borrow(
        self,
        asset: str,
        amount: float,
        *,
        symbol: str | None = None,
        isolated: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Borrow asset on cross or isolated margin."""
        mode_isolated = (
            _margin_isolated_default() if isolated is None else bool(isolated)
        )
        clean_asset = asset.upper()
        params: dict[str, Any] = {
            "asset": clean_asset,
            "amount": f"{float(amount):.8f}",
            "timestamp": _now_ms(),
            "recvWindow": get_settings().recv_window,
        }
        if mode_isolated:
            if not symbol:
                raise ValueError("margin_borrow requires symbol for isolated margin")
            params["isIsolated"] = "TRUE"
            params["symbol"] = self._clean_symbol(symbol)
        params["signature"] = self._sign(params)
        _, base_url, _ = self._resolve_market("margin")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            path = "/sapi/v1/margin/loan"
            self._log_request("POST", path, data=params)
            r = await client.post(path, data=params)
        r.raise_for_status()
        return r.json()

    async def margin_repay(
        self,
        asset: str,
        amount: float,
        *,
        symbol: str | None = None,
        isolated: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Repay borrowed asset on cross or isolated margin."""
        mode_isolated = (
            _margin_isolated_default() if isolated is None else bool(isolated)
        )
        clean_asset = asset.upper()
        params: dict[str, Any] = {
            "asset": clean_asset,
            "amount": f"{float(amount):.8f}",
            "timestamp": _now_ms(),
            "recvWindow": get_settings().recv_window,
        }
        if mode_isolated:
            if not symbol:
                raise ValueError("margin_repay requires symbol for isolated margin")
            params["isIsolated"] = "TRUE"
            params["symbol"] = self._clean_symbol(symbol)
        params["signature"] = self._sign(params)
        _, base_url, _ = self._resolve_market("margin")
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=self._settings.timeout,
            headers={"X-MBX-APIKEY": self._settings.api_key},
        ) as client:
            path = "/sapi/v1/margin/repay"
            self._log_request("POST", path, data=params)
            r = await client.post(path, data=params)
        r.raise_for_status()
        return r.json()

    async def klines(self, symbol: str, interval: str = "1m", limit: int = 30) -> list:
        try:
            path = "/fapi/v1/klines" if self._is_futures else "/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            r.raise_for_status()
            return r.json()
        except Exception:
            return []

    async def book_ticker(
        self, symbol: str, *, market: Optional[str] = None
    ) -> dict[str, Any]:
        try:
            clean = self._clean_symbol(symbol)
            market_key, base_url, is_futures = self._resolve_market(market)
            path = (
                "/fapi/v1/ticker/bookTicker"
                if is_futures
                else "/api/v3/ticker/bookTicker"
            )
            params = {"symbol": clean}
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._settings.timeout,
                headers={"X-MBX-APIKEY": self._settings.api_key},
            ) as client:
                self._log_request("GET", path, params=params)
                r = await client.get(path, params=params)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    async def my_trades_since(
        self, symbol: str, start_ms: int, *, market: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """
        Fetch account trades for a symbol since a given timestamp (ms).
        Wraps GET /api/v3/myTrades and retries common testnet throttling codes.
        """
        settings = get_settings()
        base_params = {
            "symbol": self._clean_symbol(symbol),
        }
        # Binance allows startTime/endTime filtering; we provide startTime only
        if start_ms and int(start_ms) > 0:
            base_params["startTime"] = int(start_ms)
        market_key, base_url, is_futures = self._resolve_market(market)
        if market_key == "margin" and _margin_isolated_default():
            base_params["isIsolated"] = "TRUE"
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["recvWindow"] = settings.recv_window
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    if is_futures:
                        path = "/fapi/v1/userTrades"
                    elif market_key == "margin":
                        path = "/sapi/v1/margin/myTrades"
                    else:
                        path = "/api/v3/myTrades"
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
        *,
        reduce_only: bool = False,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        clean = self._clean_symbol(symbol)
        market_key, base_url, is_futures = self._resolve_market(market)
        base_params = {
            "symbol": clean,
            "side": side,
            "type": "MARKET",
            "recvWindow": settings.recv_window,
        }
        if market_key == "options":
            base_params["quantity"] = f"{max(quantity, 0.0):.8f}"
        elif market_key == "margin":
            base_params["quantity"] = f"{quantity:.8f}"
            base_params["sideEffectType"] = os.getenv(
                "BINANCE_MARGIN_SIDE_EFFECT", "AUTO_BORROW_REPAY"
            )
            base_params["newOrderRespType"] = self._default_resp_type(market)
            if _margin_isolated_default():
                base_params["isIsolated"] = "TRUE"
        else:
            base_params["quantity"] = f"{quantity:.8f}"
            base_params["newOrderRespType"] = self._default_resp_type(market)
        if is_futures and reduce_only:
            base_params["reduceOnly"] = "true"

        if market_key == "options":
            path = "/vapi/v1/order"
        elif is_futures:
            path = "/fapi/v1/order"
        elif market_key == "margin":
            path = "/sapi/v1/margin/order"
        else:
            path = "/api/v3/order"

        # retry transient 418/429
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
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
                raise RuntimeError(
                    f"Binance error (submit_market_order) status={status} body={body}"
                ) from e

    async def submit_market_quote(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quote: float,
        *,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        market_key, base_url, is_futures = self._resolve_market(market)
        clean = self._clean_symbol(symbol)
        if market_key == "options":
            px = await self.ticker_price(clean, market=market_key)
            if px <= 0:
                raise RuntimeError(
                    f"quote too small for options: quote={quote:.8f} {clean}"
                )
            qty = max(math.floor((float(quote) / float(px)) + 1e-8), 1)
            return await self.submit_market_order(
                clean, side, float(qty), market=market_key
            )
        if is_futures:
            px = await self.ticker_price(clean, market=market_key)
            try:
                filt = await self.exchange_filter(clean, market=market_key)
                step = getattr(filt, "step_size", 0.000001) or 0.000001
                min_qty = getattr(filt, "min_qty", 0.0) or 0.0
            except Exception:
                step = 0.000001
                min_qty = 0.0
            qty_raw = max(float(quote) / float(px or 1.0), 0.0)
            factor = 1.0 / float(step)
            qty = math.floor(qty_raw * factor) / factor
            min_quote_req = max(min_qty or step, step) * float(px or 1.0)
            if quote < min_quote_req or qty <= 0:
                raise RuntimeError(
                    f"quote too small for futures: quote={quote:.8f} {clean}, required≈{min_quote_req:.4f}"
                )
            return await self.submit_market_order(clean, side, qty, market=market_key)

        settings = get_settings()
        base_params = {
            "symbol": clean,
            "side": side,
            "type": "MARKET",
            "quoteOrderQty": f"{quote:.8f}",
            "newOrderRespType": self._default_resp_type(market_key),
            "recvWindow": settings.recv_window,
        }
        if market_key == "margin":
            base_params["sideEffectType"] = os.getenv(
                "BINANCE_MARGIN_SIDE_EFFECT", "AUTO_BORROW_REPAY"
            )
            if _margin_isolated_default():
                base_params["isIsolated"] = "TRUE"
            if _margin_isolated_default():
                base_params["isIsolated"] = "TRUE"

        path = "/sapi/v1/margin/order" if market_key == "margin" else "/api/v3/order"

        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
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
                raise RuntimeError(
                    f"Binance error (submit_market_quote) status={status} body={body}"
                ) from e

    async def submit_limit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
        *,
        reduce_only: bool = False,
        market: Optional[str] = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        clean = self._clean_symbol(symbol)
        market_key, base_url, is_futures = self._resolve_market(market)
        # Enforce tick-size rounding to avoid exchange rejections
        try:
            filt = await self.exchange_filter(clean, market=market_key)
            tick = float(getattr(filt, "tick_size", 0.0) or 0.0)
        except Exception:
            tick = 0.0
        safe_price = float(price)
        if tick and tick > 0.0:
            # Round to the nearest valid tick downwards for conservatism
            steps = max(int(safe_price / tick), 0)
            safe_price = steps * tick
        base_params = {
            "symbol": clean,
            "side": side,
            "type": "LIMIT",
            "timeInForce": time_in_force,
            "quantity": f"{quantity:.8f}",
            "price": f"{safe_price:.8f}",
            "newOrderRespType": self._default_resp_type(market_key),
            "recvWindow": settings.recv_window,
        }
        if is_futures and reduce_only:
            base_params["reduceOnly"] = "true"
        if market_key == "margin":
            base_params["sideEffectType"] = os.getenv(
                "BINANCE_MARGIN_SIDE_EFFECT", "AUTO_BORROW_REPAY"
            )
        if market_key == "options":
            base_params.pop("newOrderRespType", None)
            path = "/vapi/v1/order"
        elif is_futures:
            path = "/fapi/v1/order"
        elif market_key == "margin":
            path = "/sapi/v1/margin/order"
        else:
            path = "/api/v3/order"
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
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
                raise RuntimeError(
                    f"Binance error (submit_limit_order) status={status} body={body}"
                ) from e

    async def cancel_order(
        self,
        symbol: str,
        *,
        order_id: int | str | None = None,
        client_order_id: str | None = None,
        market: Optional[str] = None,
    ) -> dict[str, Any] | None:
        if order_id is None and not client_order_id:
            raise ValueError("cancel_order requires order_id or client_order_id")

        market_key, base_url, is_futures = self._resolve_market(market)
        clean_symbol = self._clean_symbol(symbol)
        params = {
            "symbol": clean_symbol,
            "recvWindow": self._settings.recv_window,
        }
        if order_id is not None:
            params["orderId"] = str(order_id)
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        if market_key == "margin" and _margin_isolated_default():
            params["isIsolated"] = "TRUE"

        if market_key == "options":
            path = "/vapi/v1/order"
        elif is_futures:
            path = "/fapi/v1/order"
        elif market_key == "margin":
            path = "/sapi/v1/margin/order"
        else:
            path = "/api/v3/order"

        for attempt in range(3):
            signed = dict(params)
            signed["timestamp"] = _now_ms()
            signed["signature"] = self._sign(signed)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("DELETE", path, params=signed)
                    resp = await client.delete(path, params=signed)
                resp.raise_for_status()
                try:
                    return resp.json()
                except Exception:
                    return None
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in (418, 429) and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"Binance error (cancel_order) status={status} body={exc.response.text if exc.response else ''}"
                ) from exc

        return None

    async def place_reduce_only_market(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
        *,
        market: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """
        Convenience wrapper to ensure reduceOnly exits for market trims.
        Falls back to plain market order on spot venues.
        """
        market_key, _, is_futures = self._resolve_market(market)
        clean_symbol = self._clean_symbol(symbol)
        if not is_futures:
            return await self.submit_market_order(
                clean_symbol, side, quantity, market=market_key
            )
        return await self.submit_market_order(
            clean_symbol, side, quantity, reduce_only=True, market=market_key
        )

    async def amend_reduce_only_stop(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        stop_price: float,
        quantity: float,
        *,
        close_position: bool = True,
        market: Optional[str] = None,
    ) -> dict[str, Any] | None:
        """Place a reduce-only STOP_MARKET that defaults to closePosition=true."""
        market_key, base_url, is_futures = self._resolve_market(market)
        if not is_futures:
            return None
        settings = get_settings()
        clean_symbol = self._clean_symbol(symbol)
        base_params = {
            "symbol": clean_symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": f"{float(stop_price):.8f}",
            "reduceOnly": "true",
            "recvWindow": settings.recv_window,
            "newOrderRespType": "RESULT",
            "workingType": "CONTRACT_PRICE",
        }
        if close_position:
            base_params["closePosition"] = "true"
        else:
            base_params["quantity"] = f"{float(quantity):.8f}"
        for attempt in range(3):
            params = dict(base_params)
            params["timestamp"] = _now_ms()
            params["signature"] = self._sign(params)
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    path = "/fapi/v1/order"
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
                raise RuntimeError(
                    f"Binance error (amend_reduce_only_stop) status={status} body={body}"
                ) from e
        return None

    async def _post_signed(
        self,
        path: str,
        params: dict[str, Any],
        *,
        base: Literal["spot", "futures", "margin"] | None = None,
        retries: int = 3,
    ) -> Any:
        payload = dict(params or {})
        if "timestamp" not in payload:
            payload["timestamp"] = _now_ms()
        settings = get_settings()
        payload.setdefault("recvWindow", settings.recv_window)
        signature = self._sign(payload)
        signed = dict(payload)
        signed["signature"] = signature

        if base == "spot":
            base_url = self._spot_base or self._base
        elif base == "futures":
            base_url = self._futures_base or self._base
        elif base == "margin":
            base_url = self._margin_base or self._base
        else:
            base_url = self._base

        for attempt in range(max(1, retries)):
            try:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    headers={"X-MBX-APIKEY": self._settings.api_key},
                ) as client:
                    self._log_request("POST", path, data=signed)
                    resp = await client.post(path, data=signed)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in (418, 429) and attempt < (retries - 1):
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise

    async def universal_transfer(
        self, transfer_type: str, asset: str, amount: float
    ) -> dict[str, Any]:
        """Universal transfer across Binance wallets (SAPI)."""
        transfer_key = transfer_type.upper()
        if transfer_key not in TRANSFER_TYPES:
            raise ValueError(f"unsupported transfer type: {transfer_type}")
        formatted_amount = f"{float(amount):.8f}".rstrip("0").rstrip(".")
        if not formatted_amount:
            formatted_amount = "0"
        payload = {
            "type": transfer_key,
            "asset": asset.upper(),
            "amount": formatted_amount,
        }
        return await self._post_signed("/sapi/v1/asset/transfer", payload, base="spot")

    async def funding_balance(self, asset: str) -> float:
        """Fetch free balance for an asset held in the Funding wallet."""
        payload = {"asset": asset.upper()}
        try:
            data = await self._post_signed(
                "/sapi/v1/asset/get-funding-asset", payload, base="spot"
            )
        except httpx.HTTPStatusError:
            return 0.0
        if isinstance(data, list):
            for row in data:
                if (
                    isinstance(row, dict)
                    and str(row.get("asset", "")).upper() == asset.upper()
                ):
                    try:
                        return float(row.get("free") or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
        return 0.0

    async def ensure_futures_balance(
        self,
        *,
        min_fut_usdt: float,
        topup_chunk_usdt: float,
        asset: str = "USDT",
    ) -> dict[str, Any]:
        """Ensure USDⓈ-M available balance stays above threshold via Funding top-ups."""
        snapshot = await self.account_snapshot()
        available = float(snapshot.get("availableBalance") or 0.0)
        result: dict[str, Any] = {
            "ok": True,
            "skipped": False,
            "availableBalance_before": available,
        }
        if available >= float(min_fut_usdt):
            result["skipped"] = True
            return result

        funding_free = await self.funding_balance(asset)
        if funding_free <= 0.0:
            result.update(
                {"ok": False, "skipped": True, "reason": "no_funding_balance"}
            )
            return result

        transfer_amount = min(float(topup_chunk_usdt), float(funding_free))
        try:
            await self.universal_transfer("FUNDING_UMFUTURE", asset, transfer_amount)
            path = ["FUNDING_UMFUTURE"]
        except Exception as direct_err:
            try:
                await self.universal_transfer("FUNDING_MAIN", asset, transfer_amount)
                await self.universal_transfer("MAIN_UMFUTURE", asset, transfer_amount)
                path = ["FUNDING_MAIN", "MAIN_UMFUTURE"]
            except Exception as fallback_err:
                result.update(
                    {
                        "ok": False,
                        "skipped": False,
                        "error": f"{direct_err}",
                        "fallback_error": f"{fallback_err}",
                    }
                )
                return result

        snapshot_after = await self.account_snapshot()
        available_after = float(snapshot_after.get("availableBalance") or 0.0)
        result.update(
            {
                "path": path,
                "amount": transfer_amount,
                "availableBalance_after": available_after,
            }
        )
        return result


class BinanceMarginREST(BinanceREST):
    """Convenience subclass using margin endpoints by default."""

    def __init__(self) -> None:
        super().__init__(market="margin")


def _now_ms() -> int:
    return int(time.time() * 1000)
