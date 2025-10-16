from __future__ import annotations

import math
from typing import Any, Literal

from engine.config import get_settings, load_fee_config, load_ibkr_fee_config, ibkr_min_notional_usd
from engine.core.binance import BinanceREST
from engine.core.portfolio import Portfolio
from engine.core.venue_specs import SPECS, SymbolSpec
from engine.metrics import REGISTRY, orders_rejected, update_portfolio_gauges
import time

Side = Literal["BUY", "SELL"]

# Venue client registry
_CLIENTS = {}  # {"BINANCE": binance_client, "IBKR": ibkr_client}

def set_exchange_client(venue: str, client):
    _CLIENTS[venue] = client

def exchange_client(venue: str = "BINANCE"):
    return _CLIENTS.get(venue)


class OrderRouter:
    """Handles order validation and routing across multiple venues."""

    def __init__(self, default_client: BinanceREST, portfolio: Portfolio) -> None:
        self._portfolio = portfolio
        self._settings = get_settings()
        # Set the default client for backwards compatibility
        _CLIENTS["BINANCE"] = default_client

    async def initialize_balances(self) -> None:
        # Only initialize Binance balances for backwards compatibility
        # IBKR would need separate balance initialization
        if "BINANCE" in _CLIENTS:
            account = await _CLIENTS["BINANCE"].account_snapshot()
            balances = account.get("balances", [])
            for bal in balances:
                asset = bal.get("asset")
                free = float(bal.get("free", 0.0))
                locked = float(bal.get("locked", 0.0))
                total = free + locked
                if asset == "USDT":
                    self._portfolio.state.cash = total
                    self._portfolio.state.equity = total

    async def market_quote(self, symbol: str, side: Side, quote: float) -> dict[str, Any]:
        qty = await self._quote_to_quantity(symbol, side, quote)
        return await self.market_quantity(symbol, side, qty)

    def place_market_order(self, *, symbol: str, side: str, quote: float | None, quantity: float | None) -> dict[str, Any]:
        """
        Multi-venue order routing. Accepts venue-qualified symbols like "AAPL.IBKR" or "BTCUSDT.BINANCE"
        """
        # Blocking call for now - convert to async if needed
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._place_market_order_async(symbol, side, quote, quantity))
        finally:
            loop.close()

    async def _place_market_order_async(self, *, symbol: str, side: str, quote: float | None, quantity: float | None) -> dict[str, Any]:
        # Decide venue
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        # Venue auto-detection: crypto symbols default to Binance, others to IBKR
        if venue is None:
            default_venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{default_venue}"
            venue = default_venue

        client = _CLIENTS.get(venue)
        if client is None:
            raise ValueError(f"VENUE_CLIENT_MISSING: No client for venue {venue}")

        # Price lookup
        px = await _resolve_last_price(client, venue, base, symbol)
        if px is None or px <= 0:
            raise ValueError(f"NO_PRICE: No last price for {symbol}")

        # Specs lookup or fallback
        spec: SymbolSpec | None = (SPECS.get(venue) or {}).get(base)
        if venue == "IBKR" and spec is None:
            # default for US equities
            spec = SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=ibkr_min_notional_usd())
        elif venue == "BINANCE" and spec is None:
            # default for crypto
            spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)

        if spec is None:
            raise ValueError(f"SPEC_MISSING: No lot-size spec for {venue}:{base}")

        # Quote→qty or direct qty; IBKR requires integer shares
        did_round = False
        if quote is not None and (quantity is None or quantity == 0):
            raw_qty = float(quote) / float(px)
            quantity = _round_step(raw_qty, spec.step_size)
            did_round = (quantity != raw_qty)
        elif quantity is not None:
            quantity = _round_step(float(quantity), spec.step_size)
            did_round = True

        if did_round:
            REGISTRY["orders_rounded_total"].inc()

        if abs(quantity) < spec.min_qty:
            orders_rejected.inc()
            raise ValueError(f"QTY_TOO_SMALL: Rounded qty {quantity} < min_qty {spec.min_qty}")

        quantity_val = float(quantity) if quantity is not None else 0.0
        notional = abs(quantity_val) * float(px)
        min_notional = spec.min_notional
        if venue == "IBKR":
            min_notional = max(min_notional, ibkr_min_notional_usd())

        if notional < min_notional:
            orders_rejected.inc()
            raise ValueError(f"MIN_NOTIONAL: Notional {notional:.2f} below {min_notional:.2f}")

        # Submit
        if venue == "IBKR":
            # IBKR requires quantity; ignore quote
            t0 = time.time()
            res = client.place_market_order(symbol=symbol, side=side, quantity=int(quantity))
            t1 = time.time()
            try:
                REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
            except Exception:
                pass
            fill_notional = abs(res.get("filled_qty_base", quantity)) * float(res.get("avg_fill_price", px))
            fee_cfg = load_ibkr_fee_config()
            if fee_cfg.mode == "per_share":
                fee = max(fee_cfg.min_trade_fee_usd, abs(int(quantity)) * fee_cfg.per_share_usd)
            else:
                fee = (fee_cfg.bps / 10_000.0) * fill_notional
        else:
            # Binance path (direct async client)
            clean_symbol = base
            if quote is not None and (quantity is None or quantity == 0):
                submit = getattr(client, "submit_market_quote", None)
                if submit is None:
                    raise ValueError("CLIENT_MISSING_METHOD: submit_market_quote")
                t0 = time.time()
                res = await submit(symbol=clean_symbol, side=side, quote=quote)
                t1 = time.time()
            else:
                submit = getattr(client, "submit_market_order", None)
                if submit is None:
                    raise ValueError("CLIENT_MISSING_METHOD: submit_market_order")
                t0 = time.time()
                res = await submit(symbol=clean_symbol, side=side, quantity=float(quantity))
                t1 = time.time()

            try:
                REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
            except Exception:
                pass

            fee_bps = load_fee_config(venue).taker_bps
            filled_qty = float(res.get("executedQty") or res.get("filled_qty_base") or quantity)
            avg_price = float(res.get("avg_fill_price") or res.get("fills", [{}])[0].get("price", px))
            fill_notional = abs(filled_qty) * avg_price
            fee = (fee_bps / 10_000.0) * fill_notional
            res.setdefault("filled_qty_base", filled_qty)
            res.setdefault("avg_fill_price", avg_price)
            res["taker_bps"] = fee_bps

        # Apply fill to local portfolio immediately for responsive dashboards
        try:
            # Determine fill details across venues
            if venue == "IBKR":
                filled_qty_ibkr = float(res.get("filled_qty_base") or quantity or 0.0)
                avg_px_ibkr = float(res.get("avg_fill_price") or px)
                self._portfolio.apply_fill(base, side, abs(filled_qty_ibkr), avg_px_ibkr, float(fee))
            else:
                self._portfolio.apply_fill(base, side, abs(float(res.get("filled_qty_base") or filled_qty)), float(res.get("avg_fill_price") or avg_price), float(fee))
            st = self._portfolio.state
            update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except Exception:
            # Non-fatal; reconciliation will catch up later
            pass

        REGISTRY["fees_paid_total"].inc(fee)
        res["fee_usd"] = float(fee)
        res["rounded_qty"] = float(quantity)
        res["venue"] = venue
        return res

    async def market_quantity(self, symbol: str, side: Side, quantity: float) -> dict[str, Any]:
        """Backwards compatibility for existing code"""
        # For now, assume Binance if not specified
        if not "." in symbol:
            symbol = f"{symbol}.BINANCE"
        return await self._place_market_order_async(symbol=symbol, side=side, quote=None, quantity=quantity)

    async def _quote_to_quantity(self, symbol: str, side: Side, quote: float) -> float:
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        if venue is None:
            venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{venue}"

        client = _CLIENTS.get(venue)
        if client is None:
            raise ValueError(f"VENUE_CLIENT_MISSING: No client for venue {venue}")

        px = await _resolve_last_price(client, venue, base, symbol)
        if px is None or px <= 0:
            raise ValueError(f"NO_PRICE: No last price for {symbol}")

        spec: SymbolSpec | None = (SPECS.get(venue) or {}).get(base)
        if venue == "IBKR" and spec is None:
            spec = SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=ibkr_min_notional_usd())
        elif venue == "BINANCE" and spec is None:
            spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)

        if spec is None:
            raise ValueError(f"SPEC_MISSING: No lot-size spec for {venue}:{base}")

        raw_qty = float(quote) / float(px)
        qty = _round_step(raw_qty, spec.step_size)
        if qty <= 0:
            raise ValueError(f"QTY_TOO_SMALL: Quote {quote:.4f} -> qty {qty:.8f}")
        return qty

    def portfolio_snapshot(self):
        """Shim for persistence layer."""
        return self._portfolio.state.snapshot()

    def portfolio_service(self):
        """Shim for persistence layer."""
        return self._portfolio

    def exchange_client(self):
        """Shim for persistence layer."""
        return exchange_client("BINANCE")  # Default to Binance for backwards compatibility

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
    return symbol.replace(".BINANCE", "").upper()


def _round_step(value: float, step: float) -> float:
    precision = int(abs(math.log10(step))) if step < 1 else 0
    factor = 1 / step
    return math.floor(value * factor) / factor if factor != 0 else round(value, precision)


async def _resolve_last_price(client, venue: str, base: str, symbol: str) -> float | None:
    getter = getattr(client, "get_last_price", None)
    if callable(getter):
        price = getter(symbol)
        if hasattr(price, "__await__"):
            price = await price
        return price

    ticker = getattr(client, "ticker_price", None)
    if callable(ticker):
        clean = base if venue == "BINANCE" else symbol
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
    async def limit_quote(self, symbol: str, side: Side, quote: float, price: float, time_in_force: str = "IOC") -> dict[str, Any]:
        qty = await self._quote_to_quantity(symbol, side, quote)
        return await self.limit_quantity(symbol, side, qty, price, time_in_force)

    async def limit_quantity(self, symbol: str, side: Side, quantity: float, price: float, time_in_force: str = "IOC") -> dict[str, Any]:
        # Decide venue
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        if venue is None:
            default_venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{default_venue}"
            venue = default_venue

        client = _CLIENTS.get(venue)
        if client is None:
            raise ValueError(f"VENUE_CLIENT_MISSING: No client for venue {venue}")

        # Specs lookup
        spec: SymbolSpec | None = (SPECS.get(venue) or {}).get(base)
        if venue == "IBKR" and spec is None:
            spec = SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=ibkr_min_notional_usd())
        elif venue == "BINANCE" and spec is None:
            spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)
        if spec is None:
            raise ValueError(f"SPEC_MISSING: No lot-size spec for {venue}:{base}")

        # Round qty and price
        q_rounded = _round_step(float(quantity), spec.step_size)
        if abs(q_rounded) < spec.min_qty:
            orders_rejected.inc()
            raise ValueError(f"QTY_TOO_SMALL: Rounded qty {q_rounded} < min_qty {spec.min_qty}")

        # Try to get tick size from live exchange filter
        tick_size = 0.0
        try:
            filt = await _CLIENTS["BINANCE"].exchange_filter(base) if venue == "BINANCE" else None
            tick_size = float(getattr(filt, "tick_size", 0.0) or 0.0)
        except Exception:
            tick_size = 0.0
        p_rounded = _round_tick(float(price), tick_size)

        # Notional
        # Use cached/last px for notional; for limit, approximate with limit price
        px_for_notional = p_rounded if p_rounded > 0 else (await _resolve_last_price(client, venue, base, symbol) or 0)
        notional = abs(q_rounded) * float(px_for_notional)
        min_notional = spec.min_notional
        if venue == "IBKR":
            min_notional = max(min_notional, ibkr_min_notional_usd())
        if notional < min_notional:
            orders_rejected.inc()
            raise ValueError(f"MIN_NOTIONAL: Notional {notional:.2f} below {min_notional:.2f}")

        # Submit
        clean_symbol = _normalize_symbol(symbol) if venue == "BINANCE" else symbol
        submit = getattr(client, "submit_limit_order", None)
        if submit is None:
            raise ValueError("CLIENT_MISSING_METHOD: submit_limit_order")
        t0 = time.time()
        res = await submit(symbol=clean_symbol, side=side, quantity=float(q_rounded), price=float(p_rounded), time_in_force=time_in_force)
        t1 = time.time()

        try:
            REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
        except Exception:
            pass

        # Treat IOC as taker
        fee_bps = load_fee_config(venue).taker_bps
        filled_qty = float(res.get("executedQty") or res.get("filled_qty_base") or 0.0)
        avg_price = float(res.get("avg_fill_price") or res.get("fills", [{}])[0].get("price", px_for_notional))
        fill_notional = abs(filled_qty) * avg_price
        fee = (fee_bps / 10_000.0) * fill_notional
        res.setdefault("filled_qty_base", filled_qty)
        res.setdefault("avg_fill_price", avg_price)
        res["taker_bps"] = fee_bps

        # Apply fill to local portfolio (best-effort)
        try:
            if filled_qty > 0 and avg_price > 0:
                self._portfolio.apply_fill(base, side, abs(filled_qty), avg_price, float(fee))
                st = self._portfolio.state
                update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except Exception:
            pass

        REGISTRY["fees_paid_total"].inc(fee)
        res["fee_usd"] = float(fee)
        res["rounded_qty"] = float(q_rounded)
        res["venue"] = venue
        return res
