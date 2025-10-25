from __future__ import annotations

import math
from typing import Any, Literal, Optional
from time import time as _now
import httpx

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


def place_market_order(*, symbol: str, side: str, quote: float | None, quantity: float | None) -> dict[str, Any]:
    """Legacy module-level helper retained for tests/CLI scripts."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(place_market_order_async(symbol=symbol, side=side, quote=quote, quantity=quantity))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def place_market_order_async(*, symbol: str, side: str, quote: float | None, quantity: float | None) -> dict[str, Any]:
    return await _place_market_order_async_core(symbol, side, quote, quantity, None)


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
                except Exception:
                    pass

            if not balances:
                try:
                    wallet = float(account.get("totalWalletBalance") or account.get("availableBalance") or 0.0)
                    if wallet:
                        self._portfolio.state.cash = wallet
                        self._portfolio.state.equity = wallet
                except Exception:
                    pass

            self._last_snapshot = account
            self.snapshot_loaded = True
            try:
                from engine.metrics import update_portfolio_gauges
                st = self._portfolio.state
                update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
            except Exception:
                pass
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("[INIT] initialize_balances failed: %s; starting with empty balances", e)
            # Leave portfolio empty; snapshot_loaded will be false

    async def market_quote(self, symbol: str, side: Side, quote: float) -> dict[str, Any]:
        """Submit a market order using quote notional when venue supports it.

        For BINANCE we can submit `quoteOrderQty` directly which avoids requiring
        a prior price lookup (useful when public ticker endpoints are flaky).
        For other venues (e.g., IBKR) fall back to converting quote→quantity.
        """
        # Decide venue
        venue = symbol.split(".")[1] if "." in symbol else None
        base = symbol.split(".")[0].upper()

        if venue is None:
            default_venue = "BINANCE" if base.endswith("USDT") else "IBKR"
            symbol = f"{base}.{default_venue}"
            venue = default_venue

        # BINANCE fast-path: submit quote order without price lookup
        if venue == "BINANCE":
            client = _CLIENTS.get("BINANCE")
            if client is None:
                raise ValueError("VENUE_CLIENT_MISSING: No client for venue BINANCE")

            # Specs lookup or sane defaults
            spec: SymbolSpec | None = (SPECS.get("BINANCE") or {}).get(base)
            if spec is None:
                spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)

            # Notional guard (we already pass risk rails earlier but keep a venue check)
            if float(quote) < float(spec.min_notional):
                orders_rejected.inc()
                raise ValueError(f"MIN_NOTIONAL: Quote {quote:.2f} below {spec.min_notional:.2f}")

            submit = getattr(client, "submit_market_quote", None)
            if submit is None:
                # Fallback to qty path if client lacks quote submit
                qty = await self._quote_to_quantity(symbol, side, quote)
                return await self.market_quantity(symbol, side, qty)

            t0 = time.time()
            try:
                res = await submit(symbol=base, side=side, quote=float(quote))
            except httpx.HTTPStatusError as e:
                code = e.response.status_code if e.response is not None else 0
                # Some testnet symbols reject quoteOrderQty for MARKET orders
                # Gracefully fallback to quantity path on 400-series client errors
                if code in (400, 415, 422):
                    qty = await self._quote_to_quantity(symbol, side, quote)
                    return await self.market_quantity(symbol, side, qty)
                raise
            t1 = time.time()

            try:
                REGISTRY["submit_to_ack_ms"].observe((t1 - t0) * 1000.0)
            except Exception:
                pass

            # Post-process fills & fees similar to quantity path
            fee_bps = load_fee_config("BINANCE").taker_bps
            filled_qty = float(res.get("executedQty") or res.get("filled_qty_base") or 0.0)
            # Prefer avg_fill_price if present; else fall back to first fill price
            avg_price = float(res.get("avg_fill_price") or res.get("fills", [{}])[0].get("price", 0.0) or 0.0)
            fill_notional = abs(filled_qty) * avg_price if (filled_qty and avg_price) else float(quote)
            fee = (fee_bps / 10_000.0) * fill_notional
            res.setdefault("filled_qty_base", filled_qty)
            if avg_price:
                res.setdefault("avg_fill_price", avg_price)
            res["taker_bps"] = fee_bps

            # Apply fill to local portfolio (best-effort)
            try:
                if filled_qty > 0 and (avg_price or fill_notional > 0):
                    px = avg_price if avg_price else (fill_notional / max(filled_qty, 1e-12))
                    self._portfolio.apply_fill(base, side, abs(filled_qty), px, float(fee))
                    st = self._portfolio.state
                    update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
            except Exception:
                pass

            return res

        # Other venues: fall back to quote→quantity conversion
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
        # Venue routing is now handled at the app level - just pass to core function
        return await _place_market_order_async_core(symbol, side, quote, quantity, self._portfolio)
    async def market_quantity(self, symbol: str, side: Side, quantity: float) -> dict[str, Any]:
        """Backwards compatibility for existing code"""
        # For now, assume Binance if not specified
        if not "." in symbol:
            symbol = f"{symbol}.BINANCE"
        return await self._place_market_order_async(symbol=symbol, side=side, quote=None, quantity=quantity)

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
        except Exception:
            return []
        return []

    async def amend_stop_reduce_only(self, symbol: str, side: Side, stop_price: float, qty: float) -> None:
        import os, logging
        if os.getenv("ALLOW_STOP_AMEND", "").lower() not in {"1", "true", "yes"}:
            logging.getLogger(__name__).info(
                f"[STOP-AMEND:DRY] %s %s stop=%s qty=%s", symbol, side, stop_price, qty
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
        except Exception:
            pass
        api_fn = getattr(client, "amend_reduce_only_stop", None)
        if api_fn is None:
            return
        try:
            res = api_fn(symbol=symbol, side=side, stop_price=float(stop_price), quantity=float(qty))
            if hasattr(res, "__await__"):
                await res
        except Exception as e:
            # Ignore benign not-found races
            msg = str(e).upper()
            if "NOT_FOUND" in msg or "ORDER_NOT_FOUND" in msg:
                return
            return

    async def place_reduce_only_market(self, symbol: str, side: Side, qty: float):
        client = _CLIENTS.get(self._venue)
        if client is None:
            return None
        api_fn = getattr(client, "place_reduce_only_market", None)
        if api_fn is None:
            return None
        try:
            res = api_fn(symbol=symbol, side=side, quantity=float(qty))
            if hasattr(res, "__await__"):
                res = await res
            return res
        except Exception:
            return None

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
        elif venue == "KRAKEN" and spec is None:
            spec = SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0)

        if spec is None:
            raise ValueError(f"SPEC_MISSING: No lot-size spec for {venue}:{base}")

        raw_qty = float(quote) / float(px)
        if venue == "KRAKEN":
            qty = _round_step_up(raw_qty, spec.step_size)
        else:
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


async def _place_market_order_async_core(symbol: str, side: str, quote: float | None, quantity: float | None, portfolio: Optional[Portfolio]) -> dict[str, Any]:
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

    px = await _resolve_last_price(client, venue, base, symbol)
    if px is None or px <= 0:
        raise ValueError(f"NO_PRICE: No last price for {symbol}")

    spec: SymbolSpec | None = (SPECS.get(venue) or {}).get(base)
    if venue == "IBKR" and spec is None:
        spec = SymbolSpec(min_qty=1.0, step_size=1.0, min_notional=ibkr_min_notional_usd())
    elif venue == "BINANCE" and spec is None:
        spec = SymbolSpec(min_qty=0.00001, step_size=0.00001, min_notional=5.0)
    elif venue == "KRAKEN" and spec is None:
        spec = SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0)

    if spec is None:
        raise ValueError(f"SPEC_MISSING: No lot-size spec for {venue}:{base}")

    # Quote→qty or direct qty; IBKR requires integer shares
    did_round = False
    if quote is not None and (quantity is None or quantity == 0):
        raw_qty = float(quote) / float(px)
        if venue == "KRAKEN":
            quantity = _round_step_up(raw_qty, spec.step_size)
        else:
            quantity = _round_step(raw_qty, spec.step_size)
        did_round = (quantity != raw_qty)
    elif quantity is not None:
        if venue == "KRAKEN":
            quantity = _round_step_up(float(quantity), spec.step_size)
        else:
            quantity = _round_step(float(quantity), spec.step_size)
        did_round = True

    if did_round:
        REGISTRY["orders_rounded_total"].inc()

    if quantity is None or abs(quantity) < spec.min_qty:
        orders_rejected.inc()
        raise ValueError(f"QTY_TOO_SMALL: Rounded qty {quantity} < min_qty {spec.min_qty}")

    quantity_val = float(quantity)
    notional = abs(quantity_val) * float(px)
    min_notional = spec.min_notional
    if venue == "IBKR":
        min_notional = max(min_notional, ibkr_min_notional_usd())

    if notional < min_notional:
        orders_rejected.inc()
        raise ValueError(f"MIN_NOTIONAL: Notional {notional:.2f} below {min_notional:.2f}")

    if venue == "IBKR":
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
        clean_symbol = base
        if venue == "KRAKEN":
            slip = 0.002
            limit_price = px * (1 + slip) if side.upper() == "BUY" else px * (1 - slip)
            limit_price = max(limit_price, 0.0)
            submit = getattr(client, "submit_limit_order", None)
            if submit is None:
                submit = getattr(client, "submit_market_order", None)
            if submit is None:
                raise ValueError("CLIENT_MISSING_METHOD: submit_limit_order")
            t0 = time.time()
            res = await submit(symbol=clean_symbol, side=side, quantity=float(quantity), price=limit_price, time_in_force="IOC")
            t1 = time.time()
        elif quote is not None and (quantity is None or quantity == 0):
            submit = getattr(client, "submit_market_quote", None)
            if submit is None:
                raise ValueError("CLIENT_MISSING_METHOD: submit_market_quote")
            t0 = time.time()
            res = await submit(symbol=clean_symbol, side=side, quote=quote)
            t1 = time.time()
        else:
            submit = getattr(client, "submit_market_order", None)
            if submit is None:
                submit = getattr(client, "place_market_order", None)
            if submit is None:
                raise ValueError("CLIENT_MISSING_METHOD: submit_market_order")
            t0 = time.time()
            res = submit(symbol=clean_symbol, side=side, quantity=float(quantity))
            if hasattr(res, "__await__"):
                res = await res
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

    if portfolio is not None:
        try:
            if venue == "IBKR":
                filled_qty_ibkr = float(res.get("filled_qty_base") or quantity or 0.0)
                avg_px_ibkr = float(res.get("avg_fill_price") or px)
                portfolio.apply_fill(base, side, abs(filled_qty_ibkr), avg_px_ibkr, float(fee))
            else:
                filled_qty_bin = float(res.get("filled_qty_base") or quantity or 0.0)
                avg_px_bin = float(res.get("avg_fill_price") or px)
                portfolio.apply_fill(base, side, abs(filled_qty_bin), avg_px_bin, float(fee))
            st = portfolio.state
            update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except Exception:
            pass

    REGISTRY["fees_paid_total"].inc(fee)
    res["fee_usd"] = float(fee)
    res["rounded_qty"] = round(float(quantity), 8)
    res["venue"] = venue
    # Feature-gated slippage telemetry and policy (log-only)
    try:
        import os, logging
        cap_spot = float(os.getenv("SPOT_TAKER_MAX_SLIP_BPS", "25"))
        cap_fut = float(os.getenv("FUT_TAKER_MAX_SLIP_BPS", "15"))
        last_px = float(px)
        avg_px = float(res.get("avg_fill_price") or last_px)
        slip_bps = abs(avg_px - last_px) / max(last_px, 1e-12) * 10_000.0
        is_fut = (venue.upper() == "BINANCE" and os.getenv("BINANCE_MODE", "").lower().startswith("futures")) or venue.upper() == "KRAKEN"
        cap = cap_fut if is_fut else cap_spot
        if slip_bps > cap:
            logging.getLogger(__name__).warning(
                "[SLIPPAGE] %s %.1fbps > cap %.1fbps (venue=%s)", symbol, slip_bps, cap, venue
            )
            # Emit skip event for heatmap rollups
            try:
                from engine.core.event_bus import BUS
                BUS.fire("event_bo.skip", {"symbol": base, "reason": "slippage"})
            except Exception:
                pass
        # Histogram observation (optional)
        try:
            from engine.metrics import exec_slippage_bps as _slip_hist
            intent = os.getenv("SLIPPAGE_INTENT", "GENERIC")
            _slip_hist.labels(symbol=base, venue=venue, intent=intent).observe(slip_bps)
        except Exception:
            pass
        # Emit slippage sample for overrides
        try:
            from engine.core.event_bus import BUS
            BUS.fire("exec.slippage", {"symbol": base, "venue": venue, "bps": slip_bps})
        except Exception:
            pass
    except Exception:
        pass
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
    def _import_futures_positions(self, positions: list[dict] | None) -> None:
        """Populate internal portfolio from Binance futures positions.

        Expects entries with keys: symbol, positionAmt, entryPrice.
        """
        if not positions:
            return
        # Clear existing positions before import
        try:
            self._portfolio.state.positions.clear()
        except Exception:
            pass
        for p in positions:
            try:
                amt = float(p.get("positionAmt", 0.0) or 0.0)
                if abs(amt) <= 0.0:
                    continue
                sym = str(p.get("symbol", "")).upper()
                entry = float(p.get("entryPrice", 0.0) or 0.0)
                pos = self._portfolio.state.positions.setdefault(sym, self._portfolio.state.positions.get(sym))
                if pos is None:
                    from engine.core.portfolio import Position as _Position
                    pos = _Position(symbol=sym)
                    self._portfolio.state.positions[sym] = pos
                pos.quantity = amt  # signed
                pos.avg_price = entry
                # last_price updated via /portfolio marks; upl recomputed there
            except Exception:
                continue
        # After import, recalc exposure/equity; last prices will be updated on /portfolio
        try:
            from engine.core.portfolio import Portfolio as _Port
            # trigger recalc with current last prices (may be zero)
            self._portfolio._recalculate()  # type: ignore[attr-defined]
        except Exception:
            pass
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
        except Exception:
            pass

        if positions:
            try:
                self._import_futures_positions(positions)
            except Exception:
                pass

        try:
            from engine.metrics import update_portfolio_gauges
            st = self._portfolio.state
            update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
        except Exception:
            pass

        return self._last_snapshot or {"balances": [], "positions": []}

    async def get_account_snapshot(self) -> dict:
        """Shim for current snapshot (latest stored or last fetch)."""
        if self._last_snapshot is None:
            return await self.fetch_account_snapshot()
        return self._last_snapshot

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
        elif venue == "KRAKEN" and spec is None:
            spec = SymbolSpec(min_qty=0.1, step_size=0.1, min_notional=10.0)
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

    # ---- Shadow maker path for scalps (logs only; still executes taker) ----
    async def place_entry(self, symbol: str, side: Side, qty: float, *, venue: str, intent: str = ""):
        import os, logging
        # Resolve best reference prices; fall back to last
        last_px = await self.get_last_price(symbol)
        if last_px is None or last_px <= 0:
            last_px = 0.0
        # Optional risk-parity sizing override (when qty <= 0 or explicitly enabled)
        try:
            if os.getenv("RISK_PARITY_ENABLED", "").lower() in {"1", "true", "yes"} and (qty is None or qty <= 0):
                from engine.risk.sizer import risk_parity_qty, clamp_notional
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
        except Exception:
            pass
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
                    logging.getLogger(__name__).info("[CUTBACK] %s qty mult=%.2f -> %.8f", symbol, mult, qty)
                if intent.upper() == "SCALP" and not ov.scalp_enabled(symbol):
                    logging.getLogger(__name__).warning("[MUTED] SCALP disabled for %s; blocking entry", symbol)
                    return {"status": "blocked", "reason": "SCALP_MUTED", "symbol": symbol}
        except Exception:
            pass
        shadow = os.getenv("SCALP_MAKER_SHADOW", "").lower() in {"1", "true", "yes"}
        if intent.upper() == "SCALP" and shadow:
            ref = float(last_px)
            improve_bps = float(os.getenv("MAKER_PRICE_IMPROVE_BPS", "1"))
            improve = ref * improve_bps / 10_000.0
            limit_px = (ref - improve) if side == "BUY" else (ref + improve)
            tif = "IOC" if (venue.lower() == "futures" or os.getenv("BINANCE_MODE", "").lower().startswith("futures")) else "GTC"
            logging.getLogger(__name__).info(
                "[SCALP:MAKER:SHADOW] %s %s qty=%s px=%.8f tif=%s", symbol, side, qty, limit_px, tif
            )
        # Execute taker path for now (no behavior change)
        # Pre-flight min notional step guard
        try:
            import os
            min_block_usd = float(os.getenv("MIN_NOTIONAL_BLOCK_USD", os.getenv("MIN_NOTIONAL_USDT", "5")))
            q_rounded = self.round_step(symbol, float(qty))
            if (q_rounded <= 0.0) or (float(qty) * float(last_px) < min_block_usd):
                logging.getLogger(__name__).warning("[MIN_NOTIONAL_BLOCK] %s notional=%.4f below %.2f or step rounds to 0", symbol, float(qty) * float(last_px), min_block_usd)
                return {"status": "blocked", "reason": "MIN_NOTIONAL_BLOCK", "symbol": symbol}
        except Exception:
            pass
        res = await self._place_market_order_async(symbol=symbol, side=side, quote=None, quantity=qty)
        # Emit trade.fill for synchronous fills
        try:
            self._emit_fill(res, symbol=symbol.split(".")[0], side=side, venue=venue, intent=intent)
        except Exception:
            pass
        return res

    # Utility methods used by guards/sizers
    async def list_positions(self):
        out = []
        try:
            st = self._portfolio.state
            for sym, pos in (st.positions or {}).items():
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                out.append({"symbol": sym, "qty": qty})
        except Exception:
            return []
        return out

    async def set_trading_enabled(self, enabled: bool):
        try:
            # Delegate to risk_guardian flag file writer
            from engine.risk_guardian import _write_trading_flag
            _write_trading_flag(bool(enabled))
        except Exception:
            pass

    def set_preferred_quote(self, quote: str) -> None:
        try:
            self._preferred_quote = quote.upper()
        except Exception:
            self._preferred_quote = quote.upper()

    async def auto_net_hedge_btc(self, percent: float = 0.30):
        # Placeholder: calculate net delta and open a BTCUSDT opposite position; best-effort noop for now
        return None


class _MDAdapter:
    def __init__(self, router: OrderRouterExt) -> None:
        self.router = router

    def last(self, symbol: str):
        # Synchronous helper for ATR sizing path
        import asyncio
        res = asyncio.get_event_loop().run_until_complete(self.router.get_last_price(f"{symbol}.BINANCE"))
        return res

    def atr(self, symbol: str, tf: str = "5m", n: int = 14):
        # Use exchange klines to compute ATR quickly
        import math
        import asyncio
        client = self.router.exchange_client()
        if client is None or not hasattr(client, "klines"):
            return 0.0
        kl = client.klines(symbol, interval=tf, limit=max(n + 1, 15))
        if hasattr(kl, "__await__"):
            kl = asyncio.get_event_loop().run_until_complete(kl)
        if not isinstance(kl, list) or len(kl) < 2:
            return 0.0
        prev_close = None
        trs = []
        for row in kl[-(n + 1):]:
            high = float(row[2]); low = float(row[3]); close = float(row[4])
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
            base = symbol.split(".")[0].upper()
            spec = (SPECS.get(self._venue) or {}).get(base)
            step = spec.step_size if spec else 0.0
            if step <= 0:
                step = 1e-6
            return _round_step(float(qty), float(step))
        except Exception:
            return qty

    def round_tick(self, symbol: str, price: float) -> float:
        try:
            base = symbol.split(".")[0].upper()
            spec = (SPECS.get(self._venue) or {}).get(base)
            tick = getattr(spec, "tick_size", 0.0) if spec else 0.0
            return _round_tick(float(price), float(tick))
        except Exception:
            return price

    def qty_step(self, symbol: str) -> float:
        try:
            base = symbol.split(".")[0].upper()
            spec = (SPECS.get(self._venue) or {}).get(base)
            return float(spec.step_size) if spec else 1e-6
        except Exception:
            return 1e-6

    async def place_reduce_only_limit(self, symbol: str, side: Side, qty: float, price: float):
        client = _CLIENTS.get(self._venue)
        if client is None:
            return None
        submit = getattr(client, "submit_limit_order", None)
        if submit is None:
            return None
        # Best-effort; some venues accept reduceOnly param; ignore if unsupported
        params = dict(symbol=symbol.split(".")[0], side=side, quantity=float(qty), price=float(price), time_in_force="GTC")
        if "reduce_only" in submit.__code__.co_varnames:  # type: ignore[attr-defined]
            params["reduce_only"] = True  # type: ignore[index]
        res = submit(**params)
        if hasattr(res, "__await__"):
            res = await res
        return res

    # ---- Fill emitter ----
    def _emit_fill(self, res: dict[str, Any], *, symbol: str, side: str, venue: str, intent: str) -> None:
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
                bus.fire("trade.fill", payload)
        except Exception:
            pass
