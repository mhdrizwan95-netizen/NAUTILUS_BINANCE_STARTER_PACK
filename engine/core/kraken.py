from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import math
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from engine.config import get_settings

__all__ = ["KrakenREST", "KrakenAPIError"]


class KrakenAPIError(RuntimeError):
    """Raised when Kraken Futures API returns an error payload."""


class KrakenOrderQuantityError(ValueError):
    """Raised when a market order is requested with zero/negative size."""

    def __init__(self) -> None:
        super().__init__("QTY_TOO_SMALL")


class KrakenUnsupportedMethodError(KrakenAPIError):
    """Raised when a private request attempts to use an invalid HTTP method."""

    def __init__(self, method: str) -> None:
        super().__init__(f"UNSUPPORTED_METHOD: {method}")


def _now_ms() -> int:
    return int(time.time() * 1000)


_SYMBOL_ALIASES = {
    "BTCUSD": "PI_XBTUSD",
    "XBTUSD": "PI_XBTUSD",
    "PI_XBTUSD": "PI_XBTUSD",
    "ETHUSD": "PI_ETHUSD",
    "ETHUSDT": "PI_ETHUSD",
    "PI_ETHUSD": "PI_ETHUSD",
}


def _normalize_symbol(symbol: str) -> str:
    """Map human-readable symbols to Kraken Futures instrument IDs."""
    sym = symbol.split(".")[0].upper()
    return _SYMBOL_ALIASES.get(sym, sym)


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger("engine.kraken.rest").debug("%s suppressed: %s", context, exc, exc_info=True)


_BASE_URL_ERRORS: tuple[type[Exception], ...] = (httpx.InvalidURL, TypeError, ValueError)
_CLIENT_CLOSE_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, RuntimeError)
_PARSE_ERRORS: tuple[type[Exception], ...] = (TypeError, ValueError)
_PRIVATE_REQUEST_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, ValueError, OSError)
_IMPORT_ERRORS: tuple[type[Exception], ...] = (ImportError, ModuleNotFoundError)
_PORTFOLIO_STATE_ERRORS: tuple[type[Exception], ...] = (AttributeError, ValueError, KeyError)
_STORE_ERRORS: tuple[type[Exception], ...] = (AttributeError, OSError, RuntimeError, ValueError)
_REFRESH_ERRORS: tuple[type[Exception], ...] = (
    KrakenAPIError,
    httpx.HTTPError,
    RuntimeError,
    asyncio.CancelledError,
)
_POSITION_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError, KeyError)
_KRAKEN_FETCH_ERRORS: tuple[type[Exception], ...] = (
    httpx.HTTPError,
    asyncio.TimeoutError,
    ValueError,
)


class KrakenREST:
    """
    Minimal async client for Kraken Futures REST API.

    Supports accounts, open positions, mark prices, and market orders for the
    core exporter / trader flows. Kraken Futures uses HMAC-SHA512 signing with
    a SHA256(nonce + body) prefix as per their documentation.
    """

    def __init__(self) -> None:
        settings = get_settings()
        raw_base = settings.base_url or "https://demo-futures.kraken.com"
        self._base, self._api_prefix = self._split_base_and_prefix(raw_base)
        self._timeout = settings.timeout or 10.0
        self._api_key = settings.api_key or ""
        secret = settings.api_secret or ""
        self._secret_bytes = base64.b64decode(secret) if secret else b""
        self._logger = logging.getLogger("engine.kraken.rest")
        self._client = httpx.AsyncClient(base_url=self._base, timeout=self._timeout)
        self._price_cache: dict[str, float] = {}
        self._nonce_lock = threading.Lock()
        self._last_nonce = int(time.time() * 1_000_000)

    @staticmethod
    def _split_base_and_prefix(raw_base: str) -> tuple[str, str]:
        try:
            url = httpx.URL(str(raw_base))
        except _BASE_URL_ERRORS as exc:
            _log_suppressed("kraken base url parse", exc)
            return ("https://demo-futures.kraken.com", "/derivatives/api/v3")
        base = url.copy_with(path="", query=None, fragment=None)
        prefix = _normalize_prefix(url.path)
        return (str(base), prefix)

    def _api_path(self, endpoint: str) -> str:
        if not endpoint:
            return self._api_prefix
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        if endpoint.startswith(self._api_prefix):
            return endpoint
        return f"{self._api_prefix}{endpoint}"

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except _CLIENT_CLOSE_ERRORS as exc:
            _log_suppressed("kraken client close", exc)

    # ------------------------------------------------------------------ Account
    async def account_snapshot(self) -> dict[str, Any]:
        # Fallback for when credentials are invalid/missing (demo mode)
        if not self._api_key or not self._secret_bytes:
            self._logger.debug("[KRAKEN] No API credentials - using demo/fallback balances")
            return {
                "totalWalletBalance": 1000.0,
                "availableBalance": 1000.0,
                "balances": [{"asset": "USD", "free": 1000.0, "locked": 0.0}],
                "positions": [],
            }

        try:
            payload: dict[str, Any] = {}
            data = await self._private_get("/accounts", payload)

            accounts = data.get("accounts") or data.get("result", {}).get("accounts") or {}

            flex = accounts.get("flex") or {}
            cash = accounts.get("cash") or {}

            equity = _to_float(
                flex.get("portfolioValue")
                or flex.get("balanceValue")
                or flex.get("marginEquity")
                or 0.0
            )
            available = _to_float(
                flex.get("availableMargin") or cash.get("balances", {}).get("usd") or 0.0
            )
            wallet = _to_float(
                flex.get("balanceValue") or cash.get("balances", {}).get("usd") or equity
            )

            balances: list[dict[str, Any]] = []
            for asset, amt in (cash.get("balances") or {}).items():
                try:
                    free_amt = _to_float(amt)
                except _PARSE_ERRORS as exc:
                    _log_suppressed("kraken balance parse", exc)
                else:
                    balances.append({"asset": asset.upper(), "free": free_amt, "locked": 0.0})

            positions = await self.positions()
        except KrakenAPIError as exc:
            self._logger.warning("[KRAKEN] Account API failed: %s - using demo balances", exc)
            return {
                "totalWalletBalance": 1000.0,
                "availableBalance": 1000.0,
                "balances": [{"asset": "USD", "free": 1000.0, "locked": 0.0}],
                "positions": [],
            }
        else:
            return {
                "totalWalletBalance": wallet,
                "availableBalance": available,
                "balances": balances or [{"asset": "USD", "free": available, "locked": 0.0}],
                "positions": positions,
            }

    async def positions(self) -> list[dict[str, Any]]:
        if not self._api_key or not self._secret_bytes:
            return []

        try:
            payload: dict[str, Any] = {}
            data = await self._private_get("/openpositions", payload)
            raw_positions = (
                data.get("openPositions")
                or data.get("positions")
                or data.get("result", {}).get("openPositions")
                or []
            )

            formatted: list[dict[str, Any]] = []
            for pos in raw_positions:
                try:
                    symbol_raw = pos.get("instrument") or pos.get("symbol") or ""
                    symbol = _normalize_symbol(str(symbol_raw))
                    if not symbol:
                        continue
                    size = _to_float(
                        pos.get("balance")
                        or pos.get("size")
                        or pos.get("position")
                        or pos.get("qty")
                        or 0.0
                    )
                    if size == 0.0:
                        continue
                    entry_price = _to_float(
                        pos.get("entry_price")
                        or pos.get("entryPrice")
                        or pos.get("avg_entry_price")
                        or pos.get("avgEntryPrice")
                        or 0.0
                    )
                    mark_price = _to_float(
                        pos.get("mark_price")
                        or pos.get("markPrice")
                        or pos.get("indexPrice")
                        or 0.0
                    )
                    pnl = _to_float(
                        pos.get("pnl") or pos.get("unrealizedPnl") or pos.get("unRealizedProfit")
                    )
                    payload = {
                        "symbol": symbol,
                        "positionAmt": size,
                        "entryPrice": entry_price,
                        "markPrice": mark_price,
                        "pnl": pnl,
                    }
                except _PARSE_ERRORS as exc:
                    _log_suppressed("kraken position parse", exc)
                else:
                    formatted.append(payload)
        except KrakenAPIError:
            self._logger.debug("[KRAKEN] Positions API failed - returning empty positions")
            return []
        else:
            return formatted

    # ------------------------------------------------------------------ Pricing
    async def get_last_price(self, symbol: str) -> float | None:
        price = await self.ticker_price(symbol)
        if price is not None:
            return price
        return self._price_cache.get(_normalize_symbol(symbol))

    async def safe_price(self, symbol: str) -> float | None:
        """Return cached mark if available else hit /tickers and update cache."""
        canon = _normalize_symbol(symbol).split(".")[0]
        cached = self._price_cache.get(canon)
        if isinstance(cached, (int, float)) and cached > 0:
            return float(cached)
        price = await self.ticker_price(canon)
        if isinstance(price, (int, float)) and price > 0:
            self._price_cache[canon] = float(price)
            return float(price)
        return None

    async def ticker_price(self, symbol: str) -> float | None:
        # 1) Canonicalize symbol (strip any suffixes like .KRAKEN)
        canon = symbol.split(".")[0].strip().upper()

        # Check cache first (fast path for repeated calls)
        if canon in self._price_cache:
            return self._price_cache[canon]

        # 2) Fetch all tickers once and filter client-side
        data = await self._public_json("/tickers")
        if not isinstance(data, dict):
            return self._price_cache.get(canon)

        tickers = data.get("tickers") or []

        # 3) Find the matching instrument
        t = next((t for t in tickers if t.get("symbol", "").upper() == canon), None)
        if not t:
            self._logger.debug(
                "[KRAKEN] symbol %s not found in %d ticker entries", canon, len(tickers)
            )
            return None

        # 4) Return the first available price in a sensible order
        # Prefer last, then markPrice, then mid of bid/ask, then indexPrice if present.
        for k in ("last", "markPrice"):
            v = t.get(k)
            if v not in (None, "", "0"):
                try:
                    price = float(v)
                    if price > 0:
                        self._logger.debug(
                            "[KRAKEN] Found valid price for %s: %s from %s",
                            canon,
                            price,
                            k,
                        )
                        self._price_cache[canon] = price
                        return price
                except _PARSE_ERRORS as exc:
                    _log_suppressed(f"kraken price parse ({k})", exc)

        bid, ask = t.get("bid"), t.get("ask")
        if bid and ask:
            try:
                price = (float(bid) + float(ask)) / 2.0
                if price > 0:
                    self._price_cache[canon] = price
                    return price
            except _PARSE_ERRORS as exc:
                _log_suppressed("kraken bid/ask midpoint", exc)

        idx = t.get("index") or t.get("indexPrice")
        if idx not in (None, "", "0"):
            try:
                price = float(idx)
                if price > 0:
                    self._price_cache[canon] = price
                    return price
            except _PARSE_ERRORS as exc:
                _log_suppressed("kraken index price parse", exc)

        self._logger.debug(
            "[KRAKEN] no valid price found for %s in available fields: %s",
            canon,
            list(t.keys()),
        )
        return None

    # ------------------------------------------------------------------ Orders
    async def submit_market_order(
        self, *, symbol: str, side: str, quantity: float
    ) -> dict[str, Any]:
        kraken_symbol = _normalize_symbol(symbol)
        side_value = "buy" if side.upper() == "BUY" else "sell"
        size = abs(float(quantity))
        if size <= 0.0:
            raise KrakenOrderQuantityError()

        payload = {
            "orderType": "mkt",
            "symbol": kraken_symbol,
            "side": side_value,
            "size": str(size),
            "cliOrdId": str(uuid.uuid4()),
            "reduceOnly": False,
        }
        data = await self._private_post("/sendorder", payload)

        order_info = (
            data.get("order") or data.get("sendStatus") or data.get("result", {}).get("order") or {}
        )
        status = (
            order_info.get("status")
            or data.get("status")
            or data.get("result", {}).get("status")
            or "unknown"
        )
        filled = _to_float(
            order_info.get("filledSize")
            or order_info.get("filled")
            or order_info.get("size")
            or size
        )
        avg_price = _to_float(
            order_info.get("avgPrice")
            or order_info.get("fillPrice")
            or order_info.get("lastExecutionPrice")
            or order_info.get("price")
            or self._price_cache.get(kraken_symbol, 0.0)
        )

        return {
            "symbol": symbol,
            "status": str(status).upper(),
            "executedQty": filled,
            "filled_qty_base": filled,
            "avg_fill_price": avg_price,
            "raw": data,
        }

    # ------------------------------------------------------------------ Helpers
    def cache_price(self, symbol: str, price: float | None) -> None:
        if price is None:
            return
        try:
            val = float(price)
        except (TypeError, ValueError):
            return
        if not math.isfinite(val) or val <= 0.0:
            return
        canon = _normalize_symbol(symbol).split(".")[0]
        self._price_cache[canon] = val

    def _next_nonce(self) -> str:
        with self._nonce_lock:
            self._last_nonce += 1
            return str(self._last_nonce)

    async def _private_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._private_request("GET", path, params)

    async def _private_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._private_request("POST", path, payload)

    async def _private_request(
        self, method: str, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._api_key or not self._secret_bytes:
            raise KrakenAPIError("KRAKEN_API_KEYS_MISSING")

        method = method.upper()
        if method not in {"GET", "POST"}:
            raise KrakenUnsupportedMethodError(method)

        nonce = self._next_nonce()
        # Normalize parameter types and append nonce
        normalized: list[tuple[str, str]] = []
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized.append((key, "true" if value else "false"))
            else:
                normalized.append((key, str(value)))
        normalized.append(("nonce", nonce))

        if method == "GET":
            query_items = list(normalized)
            body_items: list[tuple[str, str]] = []
        else:
            query_items = []
            body_items = list(normalized)

        query_string = urlencode(query_items, doseq=True)
        body_string = urlencode(body_items, doseq=True)
        sign_path = self._api_path(path).replace("/derivatives", "", 1)
        sign_payload = f"{query_string}{body_string}{sign_path}"
        payload_hash = hashlib.sha256(sign_payload.encode("utf-8")).digest()
        signature = base64.b64encode(
            hmac.new(self._secret_bytes, payload_hash, hashlib.sha512).digest()
        ).decode()

        headers = {"APIKey": self._api_key, "Authent": signature}
        url = self._api_path(path)
        try:
            if method == "GET":
                resp = await self._client.get(url, params=query_items, headers=headers)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                resp = await self._client.post(
                    url, content=body_string.encode("utf-8"), headers=headers
                )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            self._logger.exception(
                "[KRAKEN] HTTP error %s for %s: %s",
                exc.response.status_code if exc.response else "?",
                path,
                detail,
            )
            raise KrakenAPIError(detail) from exc
        except _PRIVATE_REQUEST_ERRORS as exc:
            self._logger.exception("[KRAKEN] request failed for %s", path)
            raise KrakenAPIError(str(exc)) from exc

        # Futures API returns {"success": false, "error": [...]}
        if isinstance(data, dict):
            if data.get("success") is False:
                raise KrakenAPIError(str(data.get("error")))
            error = data.get("error") or data.get("errors")
            if error:
                raise KrakenAPIError(str(error))

        return data

    async def _public_json(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        async def _fetch():
            resp = await self._client.get(self._api_path(endpoint), params=params)
            resp.raise_for_status()
            return resp.json()

        return await self._safely_fetch(endpoint, _fetch)

    async def _safely_fetch(self, label: str, func: Callable[[], Awaitable[Any]]) -> Any | None:
        try:
            return await func()
        except _KRAKEN_FETCH_ERRORS:
            self._logger.exception("kraken fetch failed (%s)", label)
            return None

    def _sign(self, path: str, body: bytes, nonce: str) -> str:
        # Deprecated - using the new _private_post signing logic above
        digest = hashlib.sha256(nonce.encode("utf-8") + body).digest()
        mac = hmac.new(self._secret_bytes, path.encode("utf-8") + digest, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode("utf-8")

    async def open_positions(self) -> list[dict]:
        """
        Fetch open futures positions for the account.
        See https://docs.kraken.com/api/docs/futures-api/trading/get-open-positions/
        """
        if not self._api_key or not self._secret_bytes:
            self._logger.debug("KrakenREST.open_positions: no API credentials - returning empty")
            return []

        try:
            payload: dict[str, Any] = {}
            resp = await self._private_get("/openpositions", payload)
            raw_positions = resp.get("openPositions", [])
            self._logger.debug(
                "KrakenREST.open_positions -> found %s positions", len(raw_positions)
            )

            positions: list[dict[str, Any]] = []
            for pos in raw_positions:
                try:
                    symbol = _normalize_symbol(
                        str(pos.get("instrument") or pos.get("symbol") or "")
                    )
                    if not symbol:
                        continue
                    size = _to_float(
                        pos.get("balance")
                        or pos.get("size")
                        or pos.get("position")
                        or pos.get("qty")
                        or 0.0
                    )
                    if size == 0.0:
                        continue
                    entry_price = _to_float(
                        pos.get("entry_price")
                        or pos.get("entryPrice")
                        or pos.get("avg_entry_price")
                        or pos.get("avgEntryPrice")
                        or 0.0
                    )
                    mark_price = _to_float(
                        pos.get("mark_price")
                        or pos.get("markPrice")
                        or pos.get("indexPrice")
                        or 0.0
                    )
                    pnl = _to_float(
                        pos.get("pnl") or pos.get("unrealizedPnl") or pos.get("unRealizedProfit")
                    )
                    payload_pos = {
                        "symbol": symbol,
                        "positionAmt": size,
                        "entryPrice": entry_price,
                        "markPrice": mark_price,
                        "pnl": pnl,
                    }
                except _PARSE_ERRORS as exc:
                    _log_suppressed("kraken open_positions parse", exc)
                else:
                    positions.append(payload_pos)
        except (KrakenAPIError, httpx.HTTPError, ValueError) as exc:
            _log_suppressed("kraken open_positions", exc)
            return []
        else:
            return positions

    async def refresh_portfolio(self):
        """
        Called during snapshot / startup to update metrics, persistence, and portfolio state.
        """
        import os
        import sys

        from engine.metrics import (
            ENTRY_PRICE_USD,
            POSITION_SIZE,
            UPNL_USD,
            update_portfolio_gauges,
        )

        try:
            positions = await self.positions()

            main_module = sys.modules.get("engine.app")
            portfolio = getattr(main_module, "portfolio", None) if main_module else None
            store_module = getattr(main_module, "store", None) if main_module else None
            if store_module is None:
                try:
                    from engine.storage import sqlite as store_module  # type: ignore[assignment]
                except _IMPORT_ERRORS as exc:
                    _log_suppressed("kraken store module import", exc)
                    store_module = None  # type: ignore[assignment]

            if portfolio:
                try:
                    portfolio.state.positions.clear()
                except _PORTFOLIO_STATE_ERRORS as exc:
                    _log_suppressed("kraken portfolio clear", exc)

            ts_ms = _now_ms()
            unreal_total = 0.0

            for pos in positions:
                try:
                    symbol = pos.get("symbol")
                    if not symbol:
                        continue
                    base_symbol = symbol.split(".")[0]
                    qty = float(pos.get("positionAmt", 0.0) or 0.0)
                    if qty == 0.0:
                        continue
                    entry_price = float(pos.get("entryPrice", 0.0) or 0.0)
                    mark_price = float(pos.get("markPrice", entry_price) or entry_price)
                    pnl = float(pos.get("pnl", (mark_price - entry_price) * qty))

                    unreal_total += pnl

                    if portfolio:
                        try:
                            from engine.core.portfolio import Position as _Position

                            position = portfolio.state.positions.get(base_symbol)
                            if position is None:
                                position = _Position(symbol=base_symbol)
                                portfolio.state.positions[base_symbol] = position
                            position.quantity = qty
                            position.avg_price = entry_price
                            position.last_price = mark_price
                            position.upl = pnl
                        except _PORTFOLIO_STATE_ERRORS as exc:
                            self._logger.warning(
                                "KrakenREST.refresh_portfolio: failed to update position %s: %s",
                                symbol,
                                exc,
                            )

                    if store_module is not None:
                        try:
                            store_module.upsert_position(
                                "kraken",
                                base_symbol,
                                qty,
                                entry_price if entry_price else None,
                                ts_ms,
                            )
                        except _STORE_ERRORS as exc:
                            self._logger.warning(
                                "KrakenREST.refresh_portfolio: failed to persist position %s: %s",
                                symbol,
                                exc,
                            )

                    labels = {
                        "symbol": base_symbol,
                        "venue": "kraken",
                        "role": os.getenv("ROLE", "trader"),
                    }
                    POSITION_SIZE.labels(**labels).set(qty)
                    ENTRY_PRICE_USD.labels(**labels).set(entry_price)
                    UPNL_USD.labels(**labels).set(pnl)
                except _POSITION_ERRORS as exc:
                    self._logger.warning(
                        "KrakenREST.refresh_portfolio: error processing position %s (%s)",
                        pos,
                        exc,
                        exc_info=True,
                    )

            if portfolio:
                try:
                    portfolio.state.unrealized = unreal_total
                    portfolio.state.equity = (
                        float(getattr(portfolio.state, "cash", 0.0) or 0.0) + unreal_total
                    )
                except _PORTFOLIO_STATE_ERRORS as exc:
                    _log_suppressed("kraken portfolio equity update", exc)

            if store_module is not None:
                try:
                    cash = 0.0
                    if portfolio:
                        cash = float(getattr(portfolio.state, "cash", 0.0) or 0.0)
                    equity = cash + unreal_total
                    store_module.insert_equity("kraken", equity, cash, unreal_total, ts_ms)
                except _STORE_ERRORS as exc:
                    self._logger.warning(
                        "KrakenREST.refresh_portfolio: failed to persist equity snapshot: %s",
                        exc,
                    )

            if portfolio:
                try:
                    state = portfolio.state
                    update_portfolio_gauges(
                        state.cash, state.realized, state.unrealized, state.exposure
                    )
                except _PORTFOLIO_STATE_ERRORS as exc:
                    _log_suppressed("kraken portfolio gauge update", exc)

            if not positions:
                self._logger.info("KrakenREST.refresh_portfolio: no open positions returned")
        except _REFRESH_ERRORS:
            self._logger.exception("KrakenREST.refresh_portfolio failed")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return "/derivatives/api/v3"
    prefix = prefix.strip()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/") or "/derivatives/api/v3"
