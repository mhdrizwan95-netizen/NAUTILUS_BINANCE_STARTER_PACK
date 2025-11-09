from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import time
from time import time as _now
from typing import Any, Literal

import httpx

from engine.config import (
    get_settings,
    ibkr_min_notional_usd,
    load_fee_config,
    load_ibkr_fee_config,
)
from engine.core.portfolio import Portfolio
from engine.core.venue_specs import SPECS, SymbolSpec
from engine.metrics import REGISTRY, orders_rejected, update_portfolio_gauges

Side = Literal["BUY", "SELL"]

# Venue client registry
_CLIENTS = {}  # {"BINANCE": binance_client, "IBKR": ibkr_client}
_LOGGER = logging.getLogger(__name__)
_ACCOUNT_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError, KeyError)
_METRIC_ERRORS: tuple[type[Exception], ...] = (ValueError, RuntimeError)
_CLIENT_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, RuntimeError, ValueError)

try:
    from engine.adapters.common import VenueRejected  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency

    class VenueRejected(Exception):
        """Fallback when venue adapters are unavailable."""

        ...


_NETWORK_ERRORS = (httpx.HTTPError, asyncio.TimeoutError, ConnectionError)
_PARSE_ERRORS = (ValueError, KeyError, json.JSONDecodeError)
_ROUTE_ERRORS = _NETWORK_ERRORS + _PARSE_ERRORS + (RuntimeError, VenueRejected)
_DATA_ERRORS = _PARSE_ERRORS + (AttributeError, TypeError)


class MissingVenueClientError(ValueError):
    """Raised when no venue client is registered."""

    def __init__(self, venue: str) -> None:
        super().__init__(f"VENUE_CLIENT_MISSING: No client for venue {venue}")


class MinNotionalViolationError(ValueError):
    """Raised when quote falls below venue min notional."""

    def __init__(self, quote: float, min_notional: float) -> None:
        super().__init__(f"MIN_NOTIONAL: Quote {quote:.2f} below {min_notional:.2f}")


class NoPriceAvailableError(ValueError):
    """Raised when we cannot determine a last price for symbol."""

    def __init__(self, symbol: str) -> None:
        super().__init__(f"NO_PRICE: No last price for {symbol}")


class SymbolSpecMissingError(ValueError):
    """Raised when the venue lacks a symbol specification."""

    def __init__(self, venue: str, base: str) -> None:
        super().__init__(f"SPEC_MISSING: No lot-size spec for {venue}:{base}")


class QuantityTooSmallError(ValueError):
    """Raised when computed quantity falls below venue minimum."""

    def __init__(self, quantity: float | None, min_qty: float) -> None:
        super().__init__(f"QTY_TOO_SMALL: Rounded qty {quantity} < min_qty {min_qty}")


class ClientMissingMethodError(ValueError):
    """Raised when a venue client lacks a required method."""

    def __init__(self, method: str) -> None:
        super().__init__(f"CLIENT_MISSING_METHOD: {method}")


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOGGER.debug("%s suppressed exception: %s", context, exc, exc_info=True)


def _safely(label: str, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except _ROUTE_ERRORS as exc:
        _log_suppressed(label, exc)
        return None


def set_exchange_client(venue: str, client):
    _CLIENTS[venue] = client


def exchange_client(venue: str = "BINANCE"):
    return _CLIENTS.get(venue)


def place_market_order(
    *,
    symbol: str,
    side: str,
    quote: float | None,
    quantity: float | None,
    market: str | None = None,
) -> dict[str, Any]:
    """Legacy module-level helper retained for tests/CLI scripts."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            place_market_order_async(
                symbol=symbol, side=side, quote=quote, quantity=quantity, market=market
            )
        )
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def place_market_order_async(
    *,
    symbol: str,
    side: str,
    quote: float | None,
    quantity: float | None,
    market: str | None = None,
) -> dict[str, Any]:
    return await _place_market_order_async_core(symbol, side, quote, quantity, None, market=market)


def _as_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def _maybe_refresh_order_status(
    res: dict[str, Any],
    client,
    venue: str,
    clean_symbol: str,
    market: str | None = None,
) -> None:
    """Binance FUTURES often reports executedQty=0 on placement; re-query if needed."""
    if venue.upper() != "BINANCE":
        return
    if client is None:
        return
    fetch = getattr(client, "order_status", None)
    if fetch is None or not callable(fetch):
        return
    filled = _as_float(res.get("executedQty"))
    if filled > 0 or _as_float(res.get("filled_qty_base")) > 0:
        return
    order_id = res.get("orderId")
    client_order_id = res.get("clientOrderId")
    if not order_id and not client_order_id:
        return
    logger = logging.getLogger(__name__)
    logger.debug(
        "[ORDER_REFRESH_DEBUG] Entering refresh check: venue=%s client=%s filled=%s",
        venue,
        bool(client),
        filled,
    )
    logger.warning(
        "[ORDER_REFRESH] %s orderId=%s clientOrderId=%s triggered due to executedQty=0",
        clean_symbol,
        order_id,
        client_order_id,
    )
    try:
        if market is not None and "market" in fetch.__code__.co_varnames:  # type: ignore[attr-defined]
            latest = await fetch(
                symbol=clean_symbol,
                order_id=order_id,
                client_order_id=client_order_id,
                market=market,
            )
        else:
            latest = await fetch(
                symbol=clean_symbol, order_id=order_id, client_order_id=client_order_id
            )
    except _ROUTE_ERRORS as exc:
        logger.warning("[ORDER_REFRESH] status fetch failed for %s: %s", clean_symbol, exc)
        return
    logger.debug(
        "[ORDER_REFRESH_DEBUG] Refresh result: status=%s execQty=%s avgPrice=%s",
        latest.get("status"),
        latest.get("executedQty"),
        latest.get("avgPrice"),
    )
    if not isinstance(latest, dict):
        return
    for key in ("status", "cumQuote", "cumQty", "executedQty", "avgPrice"):
        if latest.get(key) is not None:
            res[key] = latest[key]
    exec_qty = _as_float(latest.get("executedQty"))
    if exec_qty > 0:
        res["filled_qty_base"] = exec_qty
        res["executedQty"] = latest.get("executedQty", exec_qty)
    avg_price = _as_float(latest.get("avgPrice"))
    if avg_price > 0:
        res["avg_fill_price"] = avg_price
    logger.warning(
        "[ORDER_REFRESH] %s orderId=%s status=%s executedQty=%s avgPrice=%s",
        clean_symbol,
        latest.get("orderId"),
        latest.get("status"),
        latest.get("executedQty"),
        latest.get("avgPrice"),
    )


class OrderRouter:
    """Handles order validation and routing across multiple venues."""

    def __init__(self, default_client, portfolio: Portfolio, venue: str | None = None) -> None:
        self._portfolio = portfolio
        self._settings = get_settings()
        self._venue = (venue or self._settings.venue).upper()
        # Register default client for this router's venue
        set_exchange_client(self._venue, default_client)
        if self._venue == "BINANCE":
            _CLIENTS["BINANCE"] = default_client
        self.snapshot_loaded = False  # NEW
        self._last_snapshot: dict | None = None

    def _split_symbol(self, symbol: str) -> tuple[str, str]:
        base = symbol.split(".")[0].upper()
        venue = (
            symbol.split(".")[1].upper() if "." in symbol and symbol.split(".")[1] else self._venue
        )
        return base, venue

    def _symbol_spec(self, symbol: str) -> tuple[SymbolSpec | None, str, str]:
        base, venue = self._split_symbol(symbol)
        spec_key = "BINANCE" if venue == "BINANCE_MARGIN" else venue
        spec: SymbolSpec | None = (SPECS.get(spec_key) or {}).get(base)
        if venue == "IBKR" and spec is None:
            spec = SymbolSpec(
                min_qty=1.0,
                step_size=1.0,
                min_notional=ibkr_min_notional_usd(),
            )
        elif venue == "BINANCE" and spec is None:
            spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)
        elif venue == "KRAKEN" and spec is None:
            spec = SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0)
        return spec, base, venue

    def round_step(self, symbol: str, qty: float) -> float:
        spec, _, _ = self._symbol_spec(symbol)
        step = float(getattr(spec, "step_size", 0.0) or 0.0)
        if step <= 0:
            step = 1e-6
        return _round_step(float(qty), step)

    def round_tick(self, symbol: str, price: float) -> float:
        spec, _, _ = self._symbol_spec(symbol)
        tick = float(getattr(spec, "tick_size", 0.0) or 0.0)
        if tick <= 0:
            return float(price)
        return _round_tick(float(price), tick)

    async def initialize_balances(self) -> None:
        client = _CLIENTS.get(self._venue)
        if client is None or not hasattr(client, "account_snapshot"):
            return
        try:
            account = await client.account_snapshot()
            balances = account.get("balances", [])
            futures_positions = account.get("positions", [])

            base_currency = "USDT" if self._venue == "BINANCE" else "USD"

            if balances:
                # Set cash/equity from matching currency balance
                for bal in balances:
                    asset = bal.get("asset")
                    free = float(bal.get("free", 0.0))
                    locked = float(bal.get("locked", 0.0))
                    total = free + locked
                    if asset and asset.upper() in {base_currency, "USD", "USDT"}:
                        self._portfolio.state.cash = total
                        self._portfolio.state.equity = total
                        break
                self._balances = balances

            if futures_positions:
                try:
                    self._import_futures_positions(futures_positions)
                except _ACCOUNT_ERRORS as exc:
                    _log_suppressed("order_router", exc)

            if not balances:
                try:
                    wallet = float(
                        account.get("totalWalletBalance") or account.get("availableBalance") or 0.0
                    )
                    if wallet:
                        self._portfolio.state.cash = wallet
                        self._portfolio.state.equity = wallet
                except _ACCOUNT_ERRORS as exc:
                    _log_suppressed("order_router", exc)

            self._last_snapshot = account
            self.snapshot_loaded = True
            try:
                from engine.metrics import update_portfolio_gauges

                st = self._portfolio.state
                update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
            except _METRIC_ERRORS as exc:
                _log_suppressed("order_router", exc)
        except _CLIENT_ERRORS as exc:
            logger = logging.getLogger(__name__)
            logger.warning(
                "[INIT] initialize_balances failed: %s; starting with empty balances", exc
            )
            # Leave portfolio empty; snapshot_loaded will be false

    async def market_quote(
        self, symbol: str, side: Side, quote: float, market: str | None = None
    ) -> dict[str, Any]:
        """Submit a market order using quote notional when venue supports it."""
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        if venue is not None:
            venue = venue.upper()

        if venue is None:
            default_venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{default_venue}"
            venue = default_venue

        market_hint = market.lower() if isinstance(market, str) and market else None
        if venue == "BINANCE_MARGIN" and not market_hint:
            market_hint = "margin"

        if venue in {"BINANCE", "BINANCE_MARGIN"}:
            client = _CLIENTS.get(venue)
            if client is None:
                raise MissingVenueClientError(venue)

            spec: SymbolSpec | None = (SPECS.get("BINANCE") or {}).get(base)
            if spec is None:
                spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)

            if float(quote) < float(spec.min_notional):
                orders_rejected.inc()
                raise MinNotionalViolationError(float(quote), float(spec.min_notional))

            submit = getattr(client, "submit_market_quote", None)
            if submit is None:
                qty = await self._quote_to_quantity(symbol, side, quote, market=market_hint)
                return await self.market_quantity(symbol, side, qty, market=market_hint)

            margin_market = "margin" if venue == "BINANCE_MARGIN" else None
            submit_market = market_hint or margin_market

            t0 = time.time()
            call_kwargs = {"symbol": base, "side": side, "quote": float(quote)}
            if submit_market is not None:
                call_kwargs["market"] = submit_market
            try:
                res = await submit(**call_kwargs)
            except TypeError:
                call_kwargs.pop("market", None)
                res = await submit(**call_kwargs)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (400, 415, 422):
                    qty = await self._quote_to_quantity(symbol, side, quote, market=submit_market)
                    return await self.market_quantity(symbol, side, qty, market=submit_market)
                raise
            t1 = time.time()

            try:
                REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
            except _METRIC_ERRORS as exc:
                _log_suppressed("order_router.metrics.submit_to_ack", exc)

            fee_bps = load_fee_config(venue).taker_bps
            filled_qty = float(res.get("executedQty") or res.get("filled_qty_base") or 0.0)
            avg_price = float(
                res.get("avg_fill_price") or res.get("fills", [{}])[0].get("price", 0.0) or 0.0
            )
            fill_notional = (
                abs(filled_qty) * avg_price if (filled_qty and avg_price) else float(quote)
            )
            fee = (fee_bps / 10_000.0) * fill_notional
            res.setdefault("filled_qty_base", filled_qty)
            if avg_price:
                res.setdefault("avg_fill_price", avg_price)
            res["taker_bps"] = fee_bps
            if submit_market:
                res.setdefault("market", submit_market)

            try:
                if filled_qty > 0 and (avg_price or fill_notional > 0):
                    px = avg_price if avg_price else (fill_notional / max(filled_qty, 1e-12))
                    symbol_key = symbol if "." in symbol else f"{base}.{venue}"
                    self._portfolio.apply_fill(
                        symbol_key,
                        side,
                        abs(filled_qty),
                        px,
                        float(fee),
                        venue=venue,
                        market=submit_market,
                    )
                    st = self._portfolio.state
                    update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
            except _ROUTE_ERRORS as exc:
                _log_suppressed("order_router.apply_fill", exc)

            await self._maybe_emit_fill(res, symbol, side, venue=venue, intent="")
            return res

        qty = await self._quote_to_quantity(symbol, side, quote, market=market_hint)
        return await self.market_quantity(symbol, side, qty, market=market_hint)

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quote: float | None,
        quantity: float | None,
        market: str | None = None,
    ) -> dict[str, Any]:
        """
        Multi-venue order routing for venue-qualified symbols such as
        "AAPL.IBKR" or "BTCUSDT.BINANCE".
        """
        # Blocking call for now - convert to async if needed
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self._place_market_order_async(symbol, side, quote, quantity, market=market)
            )
        finally:
            loop.close()

    async def _place_market_order_async(
        self,
        *,
        symbol: str,
        side: str,
        quote: float | None,
        quantity: float | None,
        market: str | None = None,
    ) -> dict[str, Any]:
        # Venue routing is now handled at the app level - just pass to core function
        ctx = getattr(self, "_strategy_pending_meta", None)
        market_hint = market
        if market_hint is None and isinstance(ctx, dict):
            market_hint = ctx.get("market") or ((ctx.get("meta") or {}).get("market"))
        return await _place_market_order_async_core(
            symbol, side, quote, quantity, self._portfolio, market=market_hint
        )

    async def market_quantity(
        self, symbol: str, side: Side, quantity: float, market: str | None = None
    ) -> dict[str, Any]:
        """Backwards compatibility for existing code"""
        # For now, assume Binance if not specified
        if "." not in symbol:
            symbol = f"{symbol}.BINANCE"
        result = await self._place_market_order_async(
            symbol=symbol, side=side, quote=None, quantity=quantity, market=market
        )
        await self._maybe_emit_fill(
            result,
            symbol,
            side,
            venue=symbol.split(".")[1] if "." in symbol else self._venue,
            intent="",
        )
        return result

    async def _maybe_emit_fill(
        self, res: dict[str, Any], symbol: str, side: Side, *, venue: str, intent: str
    ) -> None:
        emit = getattr(self, "_emit_fill", None)
        if not callable(emit):
            return
        try:
            emit(res, symbol=symbol.split(".")[0], side=side, venue=venue, intent=intent)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.emit_fill", exc)

    # ---- Safe router wrappers (capability-checked, no-throw) ----
    async def list_open_entries(self) -> list[dict]:
        client = _CLIENTS.get(self._venue)
        if client is None:
            return []
        api_fn = getattr(client, "list_open_orders", None)
        if api_fn is None:
            return []
        try:
            res = api_fn()
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, list):
                return res
        except _ROUTE_ERRORS:
            return []
        return []

    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: Any | None = None,
        client_order_id: str | None = None,
        market: str | None = None,
    ) -> bool:
        client = _CLIENTS.get(self._venue)
        if client is None:
            return False
        cancel_fn = getattr(client, "cancel_order", None)
        if cancel_fn is None:
            return False

        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["order_id"] = order_id
        if client_order_id:
            params["client_order_id"] = client_order_id
        if market:
            params["market"] = market

        try:
            res = cancel_fn(**params)
            if hasattr(res, "__await__"):
                await res  # type: ignore[func-returns-value]
        except _ROUTE_ERRORS:
            logging.getLogger(__name__).debug("cancel_order failed", exc_info=True)
            return False
        else:
            return True

    async def cancel_open_order(self, order: dict) -> bool:
        symbol = str(order.get("symbol") or "").upper()
        if not symbol:
            return False
        order_id = order.get("orderId") or order.get("order_id")
        client_order_id = order.get("clientOrderId") or order.get("client_order_id")
        market = order.get("market") or order.get("venue")
        return await self.cancel_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
            market=market,
        )

    async def amend_stop_reduce_only(
        self, symbol: str, side: Side, stop_price: float, qty: float
    ) -> None:
        import logging
        import os

        if os.getenv("ALLOW_STOP_AMEND", "").lower() not in {"1", "true", "yes"}:
            logging.getLogger(__name__).info(
                "[STOP-AMEND:DRY] %s %s stop=%s qty=%s", symbol, side, stop_price, qty
            )
            return
        client = _CLIENTS.get(self._venue)
        if client is None:
            return
        # Race guard: ensure position still open
        try:
            base = symbol.split(".")[0].upper()
            pos = getattr(self._portfolio.state, "positions", {}).get(base)
            if pos is None or abs(float(getattr(pos, "quantity", 0.0)) or 0.0) <= 0.0:
                return
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.amend_stop_guard", exc)
        api_fn = getattr(client, "amend_reduce_only_stop", None)
        if api_fn is None:
            return
        clean_symbol = symbol.split(".")[0]
        params = dict(
            symbol=clean_symbol,
            side=side,
            stop_price=float(stop_price),
            quantity=float(qty),
        )
        try:
            if "close_position" in api_fn.__code__.co_varnames:  # type: ignore[attr-defined]
                params["close_position"] = True  # type: ignore[index]
        except AttributeError as exc:
            _log_suppressed("order_router.amend_stop_close_field", exc)
        try:
            res = api_fn(**params)
            if hasattr(res, "__await__"):
                await res
        except _ROUTE_ERRORS as e:
            # Ignore benign not-found races
            msg = str(e).upper()
            if "NOT_FOUND" in msg or "ORDER_NOT_FOUND" in msg:
                return
            return

    async def place_reduce_only_market(
        self, symbol: str, side: Side, qty: float, market: str | None = None
    ):
        client = _CLIENTS.get(self._venue)
        if client is None:
            return None
        api_fn = getattr(client, "place_reduce_only_market", None)
        if api_fn is None:
            return None
        clean_symbol = symbol.split(".")[0]
        try:
            if market is not None and "market" in api_fn.__code__.co_varnames:  # type: ignore[attr-defined]
                res = api_fn(symbol=clean_symbol, side=side, quantity=float(qty), market=market)
            else:
                res = api_fn(symbol=clean_symbol, side=side, quantity=float(qty))
            if hasattr(res, "__await__"):
                res = await res
        except _ROUTE_ERRORS:
            return None
        else:
            return res

    async def _quote_to_quantity(
        self, symbol: str, side: Side, quote: float, *, market: str | None = None
    ) -> float:
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        if venue is None:
            venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{venue}"

        client = _CLIENTS.get(venue)
        if client is None:
            raise MissingVenueClientError(venue)

        market_hint = market.lower() if isinstance(market, str) and market else None
        if venue == "BINANCE_MARGIN" and not market_hint:
            market_hint = "margin"
        px = await _resolve_last_price(client, venue, base, symbol, market=market_hint)
        if px is None or px <= 0:
            raise NoPriceAvailableError(symbol)

        spec_key = "BINANCE" if venue == "BINANCE_MARGIN" else venue
        spec: SymbolSpec | None = (SPECS.get(spec_key) or {}).get(base)
        if venue == "IBKR" and spec is None:
            spec = SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=ibkr_min_notional_usd())
        elif venue in {"BINANCE", "BINANCE_MARGIN"} and spec is None:
            spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)
        elif venue == "KRAKEN" and spec is None:
            spec = SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0)
        if spec is None:
            raise SymbolSpecMissingError(venue, base)

        if spec is None:
            raise SymbolSpecMissingError(venue, base)

        raw_qty = float(quote) / float(px)
        if venue == "KRAKEN":
            qty = _round_step_up(raw_qty, spec.step_size)
        else:
            qty = _round_step(raw_qty, spec.step_size)
        if qty <= 0:
            raise QuantityTooSmallError(qty, spec.min_qty if spec else 0.0)
        return qty

    def portfolio_snapshot(self):
        """Shim for persistence layer."""
        return self._portfolio.state.snapshot()

    def portfolio_service(self):
        """Shim for persistence layer."""
        return self._portfolio

    def exchange_client(self):
        """Shim for persistence layer."""
        return exchange_client(self._venue)

    def trade_symbols(self):
        """Shim for persistence layer."""
        try:
            universe = getattr(self._portfolio, "universe", [])
            if universe:
                return universe
        except AttributeError:
            pass
        # Fallback to configured symbols
        return self._settings.allowed_symbols

    async def get_last_price(self, symbol: str) -> float | None:
        """Resolve last price for a possibly venue-suffixed symbol.

        Examples:
          - "BTCUSDT" → defaults to BINANCE
          - "BTCUSDT.BINANCE" → BINANCE
          - "AAPL.IBKR" → IBKR
        """
        venue = symbol.split(".")[1] if "." in symbol else "BINANCE"
        base = symbol.split(".")[0].upper()
        client = _CLIENTS.get(venue) or self.exchange_client()
        return await _resolve_last_price(client, venue, base, symbol)


def _normalize_symbol(symbol: str) -> str:
    return symbol.split(".")[0].upper()


def _infer_default_venue(base: str, engine_venue: str | None) -> str:
    crypto_suffixes = ("USDT", "USDC", "BUSD")
    base_up = base.upper()
    is_crypto = any(base_up.endswith(suffix) for suffix in crypto_suffixes)
    if is_crypto:
        return engine_venue or "BINANCE"
    return "IBKR"


async def _place_market_order_async_core(
    symbol: str,
    side: str,
    quote: float | None,
    quantity: float | None,
    portfolio: Portfolio | None,
    *,
    market: str | None = None,
) -> dict[str, Any]:
    # Decide venue
    venue = symbol.split(".")[1] if "." in symbol else None
    base = symbol.split(".")[0].upper()

    if venue is None:
        engine_venue = getattr(get_settings(), "venue", None)
        engine_venue = engine_venue.upper() if isinstance(engine_venue, str) else None
        default_venue = _infer_default_venue(base, engine_venue)
        symbol = f"{base}.{default_venue}"
        venue = default_venue

    client = _CLIENTS.get(venue)
    if client is None:
        raise MissingVenueClientError(venue)

    market_hint: str | None = market.lower() if isinstance(market, str) and market else None
    if venue == "BINANCE_MARGIN" and not market_hint:
        market_hint = "margin"

    px = await _resolve_last_price(client, venue, base, symbol, market=market_hint)
    if px is None or px <= 0:
        raise NoPriceAvailableError(symbol)

    spec_key = "BINANCE" if venue == "BINANCE_MARGIN" else venue
    spec: SymbolSpec | None = (SPECS.get(spec_key) or {}).get(base)
    if venue == "IBKR" and spec is None:
        spec = SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=ibkr_min_notional_usd())
    elif venue in {"BINANCE", "BINANCE_MARGIN"} and spec is None:
        spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)
    elif venue == "KRAKEN" and spec is None:
        spec = SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0)

    if spec is None:
        raise SymbolSpecMissingError(venue, base)

    step_size = float(spec.step_size)
    min_qty = float(spec.min_qty)
    min_notional = float(spec.min_notional)

    # Attempt to refine specs from live exchange filters
    filt = None
    exchange_filter = getattr(client, "exchange_filter", None)
    if exchange_filter is not None:
        try:
            maybe_filter = exchange_filter(base, market=market_hint)
            filt = await maybe_filter if inspect.isawaitable(maybe_filter) else maybe_filter
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.exchange_filter", exc)

    if filt is not None:
        step_size = float(getattr(filt, "step_size", step_size) or step_size)
        min_qty = float(getattr(filt, "min_qty", min_qty) or min_qty)
        min_notional = float(getattr(filt, "min_notional", min_notional) or min_notional)

    # Quote→qty or direct qty; IBKR requires integer shares
    did_round = False
    if quote is not None and (quantity is None or quantity == 0):
        raw_qty = float(quote) / float(px)
        if venue == "KRAKEN":
            quantity = _round_step_up(raw_qty, step_size)
        else:
            quantity = _round_step(raw_qty, step_size)
        did_round = quantity != raw_qty
    elif quantity is not None:
        if venue == "KRAKEN":
            quantity = _round_step_up(float(quantity), step_size)
        else:
            quantity = _round_step(float(quantity), step_size)
        did_round = True

    if did_round:
        REGISTRY["orders_rounded_total"].inc()

    if quantity is None or abs(quantity) < min_qty:
        orders_rejected.inc()
        raise QuantityTooSmallError(quantity, min_qty)

    quantity_val = float(quantity)
    notional = abs(quantity_val) * float(px)
    if venue == "IBKR":
        min_notional = max(min_notional, ibkr_min_notional_usd())

    if notional < min_notional:
        orders_rejected.inc()
        raise MinNotionalViolationError(notional, min_notional)

    if venue == "IBKR":
        t0 = time.time()
        res = client.place_market_order(symbol=symbol, side=side, quantity=int(quantity))
        t1 = time.time()
        try:
            REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
        except _METRIC_ERRORS as exc:
            _log_suppressed("order_router.metrics.submit_to_ack", exc)
        fill_notional = abs(res.get("filled_qty_base", quantity)) * float(
            res.get("avg_fill_price", px)
        )
        fee_cfg = load_ibkr_fee_config()
        if fee_cfg.mode == "per_share":
            fee = max(fee_cfg.min_trade_fee_usd, abs(int(quantity)) * fee_cfg.per_share_usd)
        else:
            fee = (fee_cfg.bps / 10_000.0) * fill_notional
    else:
        clean_symbol = base
        if venue == "KRAKEN":
            slip = 0.002
            limit_price = px * (1 + slip) if side.upper() == "BUY" else px * (1 - slip)
            limit_price = max(limit_price, 0.0)
            submit = getattr(client, "submit_limit_order", None)
            if submit is None:
                submit = getattr(client, "submit_market_order", None)
            if submit is None:
                raise ClientMissingMethodError("submit_limit_order")
            t0 = time.time()
            res = await submit(
                symbol=clean_symbol,
                side=side,
                quantity=float(quantity),
                price=limit_price,
                time_in_force="IOC",
            )
            t1 = time.time()
        elif quote is not None and (quantity is None or quantity == 0):
            submit = getattr(client, "submit_market_quote", None)
            if submit is None:
                raise ClientMissingMethodError("submit_market_quote")
            t0 = time.time()
            call_kwargs = {"symbol": clean_symbol, "side": side, "quote": quote}
            if market_hint is not None:
                call_kwargs["market"] = market_hint
            try:
                res = await submit(**call_kwargs)
            except TypeError:
                call_kwargs.pop("market", None)
                res = await submit(**call_kwargs)
            t1 = time.time()
        else:
            submit = getattr(client, "submit_market_order", None)
            if submit is None:
                submit = getattr(client, "place_market_order", None)
            if submit is None:
                raise ClientMissingMethodError("submit_market_order")
            t0 = time.time()
            call_kwargs = {
                "symbol": clean_symbol,
                "side": side,
                "quantity": float(quantity),
            }
            if market_hint is not None:
                call_kwargs["market"] = market_hint
            try:
                res = submit(**call_kwargs)
            except TypeError:
                call_kwargs.pop("market", None)
                res = submit(**call_kwargs)
            if hasattr(res, "__await__"):
                res = await res
            t1 = time.time()

        # Futures API commonly reports NEW+executedQty=0 even when filled; quickly re-query
        try:
            await _maybe_refresh_order_status(res, client, venue, clean_symbol, market_hint)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.refresh_status", exc)

        try:
            REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
        except _METRIC_ERRORS as exc:
            _log_suppressed("order_router.metrics.submit_to_ack", exc)

        fee_bps = load_fee_config(venue).taker_bps
        filled_qty = _as_float(res.get("executedQty"))
        if filled_qty <= 0:
            filled_qty = _as_float(res.get("filled_qty_base"))
        if filled_qty <= 0 and quantity is not None:
            filled_qty = float(quantity)
        fills = res.get("fills", [{}])
        avg_price = _as_float(res.get("avg_fill_price"))
        if avg_price <= 0 and fills:
            avg_price = _as_float(fills[0].get("price"))
        if avg_price <= 0:
            avg_price = float(px)
        fill_notional = abs(filled_qty) * avg_price
        fee = (fee_bps / 10_000.0) * fill_notional
        res.setdefault("filled_qty_base", filled_qty)
        res.setdefault("avg_fill_price", avg_price)
        res["taker_bps"] = fee_bps

    if portfolio is not None:
        try:
            if venue == "IBKR":
                filled_qty_ibkr = float(res.get("filled_qty_base") or quantity or 0.0)
                avg_px_ibkr = float(res.get("avg_fill_price") or px)
                symbol_key = symbol if "." in symbol else f"{base}.{venue}"
                portfolio.apply_fill(
                    symbol_key,
                    side,
                    abs(filled_qty_ibkr),
                    avg_px_ibkr,
                    float(fee),
                    venue=venue,
                    market=market_hint,
                )
            else:
                filled_qty_bin = float(res.get("filled_qty_base") or quantity or 0.0)
                avg_px_bin = float(res.get("avg_fill_price") or px)
                symbol_key = symbol if "." in symbol else f"{base}.{venue}"
                effective_market = market_hint or ("margin" if venue == "BINANCE_MARGIN" else None)
                portfolio.apply_fill(
                    symbol_key,
                    side,
                    abs(filled_qty_bin),
                    avg_px_bin,
                    float(fee),
                    venue=venue,
                    market=effective_market,
                )
            st = portfolio.state
            update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.apply_fill", exc)

    REGISTRY["fees_paid_total"].inc(fee)
    res["fee_usd"] = float(fee)
    res["rounded_qty"] = round(float(quantity), 8)
    res["venue"] = venue
    if market_hint:
        res.setdefault("market", market_hint)
    # Feature-gated slippage telemetry and policy (log-only)
    try:
        import os

        cap_spot = float(os.getenv("SPOT_TAKER_MAX_SLIP_BPS", "25"))
        cap_fut = float(os.getenv("FUT_TAKER_MAX_SLIP_BPS", "15"))
        last_px = float(px)
        avg_px = float(res.get("avg_fill_price") or last_px)
        slip_bps = abs(avg_px - last_px) / max(last_px, 1e-12) * 10_000.0
        is_fut = (
            venue.upper() == "BINANCE"
            and (
                (market_hint == "futures")
                or (
                    market_hint is None
                    and os.getenv("BINANCE_MODE", "").lower().startswith("futures")
                )
            )
        ) or venue.upper() == "KRAKEN"
        cap = cap_fut if is_fut else cap_spot
        if slip_bps > cap:
            logging.getLogger(__name__).warning(
                "[SLIPPAGE] %s %.1fbps > cap %.1fbps (venue=%s)",
                symbol,
                slip_bps,
                cap,
                venue,
            )
            # Emit skip event for heatmap rollups
            try:
                from engine.core.event_bus import BUS

                BUS.fire("event_bo.skip", {"symbol": base, "reason": "slippage"})
            except _ROUTE_ERRORS as exc:
                _log_suppressed("order_router.slippage.skip_event", exc)
        # Histogram observation (optional)
        try:
            from engine.metrics import exec_slippage_bps as _slip_hist

            intent = os.getenv("SLIPPAGE_INTENT", "GENERIC")
            _slip_hist.labels(symbol=base, venue=venue, intent=intent).observe(slip_bps)
        except _METRIC_ERRORS as exc:
            _log_suppressed("order_router.slippage.histogram", exc)
        # Emit slippage sample for overrides
        try:
            from engine.core.event_bus import BUS

            BUS.fire("exec.slippage", {"symbol": base, "venue": venue, "bps": slip_bps})
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.slippage.emit", exc)
    except _ROUTE_ERRORS as exc:
        _log_suppressed("order_router.slippage.block", exc)
    return res


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    factor = 1 / step
    return round(value * factor) / factor


def _round_step_up(value: float, step: float) -> float:
    if step <= 0:
        return value
    factor = 1 / step
    return math.ceil(value * factor) / factor


async def _resolve_last_price(
    client, venue: str, base: str, symbol: str, *, market: str | None = None
) -> float | None:
    getter = getattr(client, "get_last_price", None)
    if callable(getter):
        try:
            price = getter(symbol, market=market)
        except TypeError:
            price = getter(symbol)
        if hasattr(price, "__await__"):
            price = await price
        return price

    ticker = getattr(client, "ticker_price", None)
    if callable(ticker):
        clean = base if venue in {"BINANCE", "BINANCE_MARGIN"} else symbol
        try:
            price = ticker(clean, market=market)
        except TypeError:
            price = ticker(clean)
        if hasattr(price, "__await__"):
            price = await price
        return price

    return None


def _round_tick(value: float, tick: float) -> float:
    if tick and tick > 0:
        precision = int(abs(math.log10(tick))) if tick < 1 else 0
        factor = 1 / tick
        return math.floor(value * factor) / factor if factor != 0 else round(value, precision)
    return value


class OrderRouterExt(OrderRouter):
    def _import_futures_positions(self, positions: list[dict] | None) -> None:
        """Populate internal portfolio from Binance futures positions.

        Expects entries with keys: symbol, positionAmt, entryPrice.
        """
        if not positions:
            return
        # Clear existing positions before import
        try:
            self._portfolio.state.positions.clear()
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.positions.clear", exc)
        for p in positions:
            try:
                amt = float(p.get("positionAmt", 0.0) or 0.0)
                if abs(amt) <= 0.0:
                    continue
                sym = str(p.get("symbol", "")).upper()
                entry = float(p.get("entryPrice", 0.0) or 0.0)
            except _PARSE_ERRORS as exc:
                _log_suppressed("order_router.position_import.parse", exc)
                continue
            pos = self._portfolio.state.positions.setdefault(
                sym, self._portfolio.state.positions.get(sym)
            )
            if pos is None:
                from engine.core.portfolio import Position as _Position

                pos = _Position(symbol=sym)
                self._portfolio.state.positions[sym] = pos
            pos.quantity = amt  # signed
            pos.avg_price = entry
            # last_price updated via /portfolio marks; upl recomputed there
        # After import, recalc exposure/equity; last prices will be updated on /portfolio
        try:
            # trigger recalc with current last prices (may be zero)
            self._portfolio._recalculate()  # type: ignore[attr-defined]
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.positions.recalc", exc)

    async def fetch_account_snapshot(self) -> dict:
        """
        Fetch a fresh snapshot from the venue and update local cache.
        Used by /account_snapshot?force=1 and any ad-hoc refreshers.
        """
        client = _CLIENTS.get(self._venue)
        if client is None or not hasattr(client, "account_snapshot"):
            return self._last_snapshot or {"balances": [], "positions": []}

        account = await client.account_snapshot()

        balances = account.get("balances", []) if isinstance(account, dict) else []
        positions = account.get("positions", []) if isinstance(account, dict) else []

        self._balances = balances
        self._positions = positions
        self._last_snapshot = account
        self.snapshot_loaded = True

        base_currency = "USDT" if self._venue == "BINANCE" else "USD"

        try:
            if balances:
                total = 0.0
                for bal in balances:
                    asset = (bal.get("asset") or "").upper()
                    if asset in {base_currency, "USD", "USDT"}:
                        total = float(bal.get("free", 0.0)) + float(bal.get("locked", 0.0))
                        break
                if total > 0:
                    self._portfolio.state.cash = total
                    self._portfolio.state.equity = total
                    from engine.metrics import update_portfolio_gauges

                    s = self._portfolio.state
                    update_portfolio_gauges(s.cash, s.realized, s.unrealized, s.exposure)
            else:
                wallet = float(
                    account.get("totalWalletBalance")
                    or account.get("availableBalance")
                    or account.get("availableMargin")
                    or 0.0
                )
                if wallet > 0:
                    self._portfolio.state.cash = wallet
                    self._portfolio.state.equity = wallet
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.snapshot.cash", exc)

        if positions:
            try:
                self._import_futures_positions(positions)
            except _ROUTE_ERRORS as exc:
                _log_suppressed("order_router.snapshot.import", exc)

        try:
            from engine.metrics import update_portfolio_gauges

            st = self._portfolio.state
            update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except _METRIC_ERRORS as exc:
            _log_suppressed("order_router.snapshot.metrics", exc)

        return self._last_snapshot or {"balances": [], "positions": []}

    async def get_account_snapshot(self) -> dict:
        """Shim for current snapshot (latest stored or last fetch)."""
        if self._last_snapshot is None:
            return await self.fetch_account_snapshot()
        return self._last_snapshot

    async def limit_quote(
        self,
        symbol: str,
        side: Side,
        quote: float,
        price: float,
        time_in_force: str = "IOC",
        *,
        market: str | None = None,
    ) -> dict[str, Any]:
        qty = await self._quote_to_quantity(symbol, side, quote, market=market)
        return await self.limit_quantity(symbol, side, qty, price, time_in_force, market=market)

    async def limit_quantity(
        self,
        symbol: str,
        side: Side,
        quantity: float,
        price: float,
        time_in_force: str = "IOC",
        *,
        market: str | None = None,
    ) -> dict[str, Any]:
        # Decide venue
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        if venue is not None:
            venue = venue.upper()

        if venue is None:
            default_venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{default_venue}"
            venue = default_venue

        client = _CLIENTS.get(venue)
        if client is None:
            raise MissingVenueClientError(venue)

        # Specs lookup
        spec, base, venue = self._symbol_spec(symbol)
        if spec is None:
            raise SymbolSpecMissingError(venue, base)

        # Round qty and price
        q_rounded = _round_step(float(quantity), spec.step_size)
        if abs(q_rounded) < spec.min_qty:
            orders_rejected.inc()
            raise QuantityTooSmallError(q_rounded, spec.min_qty)

        # Try to get tick size from live exchange filter
        tick_size = 0.0
        try:
            spec_key = "BINANCE" if venue == "BINANCE_MARGIN" else venue
            filt = (
                await _CLIENTS["BINANCE"].exchange_filter(base) if spec_key == "BINANCE" else None
            )
            tick_size = float(getattr(filt, "tick_size", 0.0) or 0.0)
        except _ROUTE_ERRORS:
            tick_size = 0.0
        p_rounded = _round_tick(float(price), tick_size)

        # Notional
        # Use cached/last px for notional; for limit, approximate with limit price
        px_for_notional = (
            p_rounded
            if p_rounded > 0
            else (
                await _resolve_last_price(
                    client,
                    venue,
                    base,
                    symbol,
                    market=(market.lower() if isinstance(market, str) and market else None),
                )
                or 0
            )
        )
        notional = abs(q_rounded) * float(px_for_notional)
        min_notional = spec.min_notional
        if venue == "IBKR":
            min_notional = max(min_notional, ibkr_min_notional_usd())
        if notional < min_notional:
            orders_rejected.inc()
            raise MinNotionalViolationError(notional, min_notional)

        # Submit
        clean_symbol = _normalize_symbol(symbol) if venue == "BINANCE" else symbol
        submit = getattr(client, "submit_limit_order", None)
        if submit is None:
            raise ClientMissingMethodError("submit_limit_order")
        t0 = time.time()
        submit_kwargs = dict(
            symbol=clean_symbol,
            side=side,
            quantity=float(q_rounded),
            price=float(p_rounded),
            time_in_force=time_in_force,
        )
        effective_market = market.lower() if isinstance(market, str) else None
        if not effective_market and venue == "BINANCE_MARGIN":
            effective_market = "margin"
        if venue in {"BINANCE", "BINANCE_MARGIN"} and effective_market is not None:
            submit_kwargs["market"] = effective_market
        try:
            res = await submit(**submit_kwargs)
        except TypeError:
            submit_kwargs.pop("market", None)
            res = await submit(**submit_kwargs)
        t1 = time.time()

        try:
            REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
        except _METRIC_ERRORS as exc:
            _log_suppressed("order_router.metrics.submit_to_ack", exc)

        # Treat IOC as taker
        fee_bps = load_fee_config(venue).taker_bps
        filled_qty = float(res.get("executedQty") or res.get("filled_qty_base") or 0.0)
        avg_price = float(
            res.get("avg_fill_price") or res.get("fills", [{}])[0].get("price", px_for_notional)
        )
        fill_notional = abs(filled_qty) * avg_price
        fee = (fee_bps / 10_000.0) * fill_notional
        res.setdefault("filled_qty_base", filled_qty)
        res.setdefault("avg_fill_price", avg_price)
        res["taker_bps"] = fee_bps

        # Apply fill to local portfolio (best-effort)
        try:
            if filled_qty > 0 and avg_price > 0:
                symbol_key = symbol if "." in symbol else f"{base}.{venue}"
                if not effective_market and venue == "BINANCE_MARGIN":
                    effective_market = "margin"
                self._portfolio.apply_fill(
                    symbol_key,
                    side,
                    abs(filled_qty),
                    avg_price,
                    float(fee),
                    venue=venue,
                    market=effective_market,
                )
                st = self._portfolio.state
                update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.shadow.apply_fill", exc)

        REGISTRY["fees_paid_total"].inc(fee)
        res["fee_usd"] = float(fee)
        res["rounded_qty"] = float(q_rounded)
        res["venue"] = venue
        return res

    # ---- Shadow maker path for scalps (logs only; still executes taker) ----
    async def place_entry(
        self,
        symbol: str,
        side: Side,
        qty: float,
        *,
        venue: str,
        intent: str = "",
        market: str | None = None,
    ):
        import logging
        import os

        market_hint = market.lower() if isinstance(market, str) and market else None
        resolved_venue = symbol.split(".")[1] if "." in symbol else venue
        base_symbol = symbol.split(".")[0].upper()
        # Resolve best reference prices; fall back to last
        last_px = await self.get_last_price(symbol)
        if market_hint:
            try:
                client = _CLIENTS.get(resolved_venue) or self.exchange_client()
                market_px = (
                    await _resolve_last_price(
                        client, resolved_venue, base_symbol, symbol, market=market_hint
                    )
                    if client
                    else None
                )
                if market_px and market_px > 0:
                    last_px = market_px
            except _ROUTE_ERRORS as exc:
                _log_suppressed("order_router.place_entry.market_px", exc)
        if last_px is None or last_px <= 0:
            last_px = 0.0
        # Optional risk-parity sizing override (when qty <= 0 or explicitly enabled)
        try:
            if os.getenv("RISK_PARITY_ENABLED", "").lower() in {
                "1",
                "true",
                "yes",
            } and (qty is None or qty <= 0):
                from engine.risk.sizer import clamp_notional, risk_parity_qty

                md = _MDAdapter(self)
                tf = os.getenv("RISK_PARITY_TF", "5m")
                n = int(float(os.getenv("RISK_PARITY_N", "14")))
                per_risk = float(os.getenv("PER_TRADE_RISK_USD", os.getenv("PER_TRADE_USD", "40")))
                computed = risk_parity_qty(per_risk, md, symbol.split(".")[0], tf, n)
                if computed > 0 and last_px > 0:
                    min_usd = float(os.getenv("RISK_PARITY_MIN_NOTIONAL_USD", "20"))
                    max_usd = float(os.getenv("RISK_PARITY_MAX_NOTIONAL_USD", "500"))
                    qty = clamp_notional(computed, last_px, min_usd, max_usd)
                    logging.getLogger(__name__).info("[RISK-PARITY] %s qty=%.8f", symbol, qty)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.place_entry.risk_parity", exc)
        # Apply auto cutback/mute (feature-gated)
        try:
            if os.getenv("AUTO_CUTBACK_ENABLED", "").lower() in {"1", "true", "yes"}:
                from engine.execution.venue_overrides import VenueOverrides

                if not hasattr(self, "_overrides"):
                    self._overrides = VenueOverrides()  # type: ignore[attr-defined]
                ov = self._overrides  # type: ignore[attr-defined]
                mult = float(ov.get_size_mult(symbol))
                if mult and mult > 0 and mult != 1.0:
                    qty = float(qty) * mult
                    logging.getLogger(__name__).info(
                        "[CUTBACK] %s qty mult=%.2f -> %.8f", symbol, mult, qty
                    )
                if intent.upper() == "SCALP" and not ov.scalp_enabled(symbol):
                    logging.getLogger(__name__).warning(
                        "[MUTED] SCALP disabled for %s; blocking entry", symbol
                    )
                    return {
                        "status": "blocked",
                        "reason": "SCALP_MUTED",
                        "symbol": symbol,
                    }
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.place_entry.cutback", exc)
        shadow = os.getenv("SCALP_MAKER_SHADOW", "").lower() in {"1", "true", "yes"}
        if intent.upper() == "SCALP" and shadow:
            ref = float(last_px)
            improve_bps = float(os.getenv("MAKER_PRICE_IMPROVE_BPS", "1"))
            improve = ref * improve_bps / 10_000.0
            limit_px = (ref - improve) if side.upper() == "BUY" else (ref + improve)
            tif = (
                "IOC"
                if (
                    venue.lower() == "futures"
                    or os.getenv("BINANCE_MODE", "").lower().startswith("futures")
                )
                else "GTC"
            )
            logging.getLogger(__name__).info(
                "[SCALP:MAKER:SHADOW] %s %s qty=%s px=%.8f tif=%s",
                symbol,
                side,
                qty,
                limit_px,
                tif,
            )
        # Execute taker path for now (no behavior change)
        # Pre-flight min notional step guard
        try:
            import os

            min_block_usd = float(
                os.getenv("MIN_NOTIONAL_BLOCK_USD", os.getenv("MIN_NOTIONAL_USDT", "5"))
            )
            q_rounded = self.round_step(symbol, float(qty))
            if (q_rounded <= 0.0) or (float(qty) * float(last_px) < min_block_usd):
                logging.getLogger(__name__).warning(
                    "[MIN_NOTIONAL_BLOCK] %s notional=%.4f below %.2f or step rounds to 0",
                    symbol,
                    float(qty) * float(last_px),
                    min_block_usd,
                )
                return {
                    "status": "blocked",
                    "reason": "MIN_NOTIONAL_BLOCK",
                    "symbol": symbol,
                }
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.place_entry.min_block", exc)
        res = await self._place_market_order_async(
            symbol=symbol, side=side, quote=None, quantity=qty, market=market_hint
        )
        # Emit trade.fill for synchronous fills
        try:
            self._emit_fill(res, symbol=symbol.split(".")[0], side=side, venue=venue, intent=intent)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.place_entry.emit", exc)
        return res

    # Utility methods used by guards/sizers
    async def list_positions(self):
        out = []
        try:
            st = self._portfolio.state
            for sym, pos in (st.positions or {}).items():
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                out.append({"symbol": sym, "qty": qty})
        except _ROUTE_ERRORS:
            return []
        return out

    async def set_trading_enabled(self, enabled: bool):
        try:
            # Delegate to risk_guardian flag file writer
            from engine.risk_guardian import _write_trading_flag

            _write_trading_flag(bool(enabled))
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.set_trading_enabled", exc)

    def set_preferred_quote(self, quote: str) -> None:
        try:
            self._preferred_quote = quote.upper()
        except AttributeError:
            self._preferred_quote = quote.upper()

    async def auto_net_hedge_btc(self, percent: float = 0.30):
        # Placeholder: calculate net delta and open a BTCUSDT hedge (best-effort noop)
        return None


class _MDAdapter:
    def __init__(self, router: OrderRouterExt) -> None:
        self.router = router
        self._venue = getattr(router, "_venue", "BINANCE")

    def _default_symbol(self, symbol: str) -> str:
        if "." in symbol and symbol.split(".")[1]:
            return symbol
        return f"{symbol}.{self._venue}"

    def last(self, symbol: str):
        # Synchronous helper for ATR sizing path
        import asyncio

        sym = self._default_symbol(symbol)
        res = asyncio.get_event_loop().run_until_complete(self.router.get_last_price(sym))
        return res

    def atr(self, symbol: str, tf: str = "5m", n: int = 14):
        # Use exchange klines to compute ATR quickly
        import asyncio

        client = self.router.exchange_client()
        if client is None or not hasattr(client, "klines"):
            return 0.0
        sym = self._default_symbol(symbol)
        base, venue = sym.split(".")
        target = base if venue == "BINANCE" else sym
        kl = client.klines(target, interval=tf, limit=max(n + 1, 15))
        if hasattr(kl, "__await__"):
            kl = asyncio.get_event_loop().run_until_complete(kl)
        if not isinstance(kl, list) or len(kl) < 2:
            return 0.0
        prev_close = None
        trs = []
        for row in kl[-(n + 1) :]:
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            if prev_close is None:
                tr = high - low
            else:
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        if len(trs) <= 1:
            return 0.0
        trs = trs[1:]
        return sum(trs) / len(trs)

    # ---- Rounding helpers ----
    def round_step(self, symbol: str, qty: float) -> float:
        try:
            sym = self._default_symbol(symbol)
            return self.router.round_step(sym, qty)
        except _DATA_ERRORS:
            return qty

    def round_tick(self, symbol: str, price: float) -> float:
        try:
            sym = self._default_symbol(symbol)
            return self.router.round_tick(sym, price)
        except _DATA_ERRORS:
            return price

    def qty_step(self, symbol: str) -> float:
        try:
            sym = self._default_symbol(symbol)
            spec, _, _ = self.router._symbol_spec(sym)
            return float(getattr(spec, "step_size", 1e-6)) if spec else 1e-6
        except _DATA_ERRORS:
            return 1e-6

    async def place_reduce_only_limit(self, symbol: str, side: Side, qty: float, price: float):
        client = _CLIENTS.get(self._venue)
        if client is None:
            return None
        submit = getattr(client, "submit_limit_order", None)
        if submit is None:
            return None
        # Best-effort; some venues accept reduceOnly param; ignore if unsupported
        params = dict(
            symbol=symbol.split(".")[0],
            side=side,
            quantity=float(qty),
            price=float(price),
            time_in_force="GTC",
        )
        if "reduce_only" in submit.__code__.co_varnames:  # type: ignore[attr-defined]
            params["reduce_only"] = True  # type: ignore[index]
        res = submit(**params)
        if hasattr(res, "__await__"):
            res = await res
        return res

    # ---- Fill emitter ----
    def _emit_fill(
        self, res: dict[str, Any], *, symbol: str, side: str, venue: str, intent: str
    ) -> None:
        try:
            bus = getattr(self, "_bus", None) or getattr(self, "bus", None)
            if not bus:
                return
            filled = float(res.get("filled_qty_base") or res.get("executedQty") or 0.0)
            avg = float(res.get("avg_fill_price") or res.get("avgPrice") or 0.0)
            if filled and avg:
                payload = {
                    "ts": float(res.get("ts") or _now()),
                    "symbol": symbol,
                    "side": side,
                    "venue": venue,
                    "intent": intent or "GENERIC",
                    "order_id": res.get("order_id") or res.get("orderId"),
                    "filled_qty": float(filled),
                    "avg_price": float(avg),
                }
                ctx = getattr(self, "_strategy_pending_meta", None)
                if isinstance(ctx, dict):
                    meta = ctx.get("meta")
                    if isinstance(meta, dict):
                        payload["strategy_meta"] = meta
                    tag = ctx.get("tag")
                    if tag is not None:
                        payload["strategy_tag"] = tag
                    ctx_side = ctx.get("side")
                    if ctx_side is not None:
                        payload["strategy_side"] = ctx_side
                    ctx_symbol = ctx.get("symbol")
                    if ctx_symbol is not None:
                        payload["strategy_symbol"] = ctx_symbol
                    try:
                        if getattr(self, "_strategy_pending_meta", None) is ctx:
                            delattr(self, "_strategy_pending_meta")
                    except AttributeError:
                        pass
                    except _ROUTE_ERRORS:
                        try:
                            self._strategy_pending_meta = None
                        except _ROUTE_ERRORS as exc:
                            _log_suppressed("order_router.strategy_meta.clear", exc)
                bus.fire("trade.fill", payload)
        except _ROUTE_ERRORS as exc:
            _log_suppressed("order_router.emit_fill", exc)
