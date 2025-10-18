from __future__ import annotations

import asyncio
import time
import json
import logging
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
import json
import httpx as _httpx

import os
from engine.config import get_settings, load_risk_config, QUOTE_CCY
from engine.core.binance import BinanceREST
from engine.core.order_router import OrderRouter, set_exchange_client
from engine.core.order_router import OrderRouterExt
from engine.core.portfolio import Portfolio
from engine.core.event_bus import BUS, initialize_event_bus, publish_order_event, publish_risk_event
from engine.core import alert_daemon
from engine.risk import RiskRails
from engine import metrics
from engine.idempotency import CACHE, append_jsonl
from engine.state import SnapshotStore
from engine.reconcile import reconcile_since_snapshot
from engine import strategy
from engine.universe import configured_universe, last_prices

app = FastAPI(title="HMM Engine", version="0.1.0")

settings = get_settings()
ROLE = os.getenv("ROLE", "trader").lower()
IS_EXPORTER = ROLE == "exporter"
VENUE = os.getenv("VENUE", "BINANCE").upper()
risk_cfg = load_risk_config()
RAILS = RiskRails(risk_cfg)


class _DummyBinanceREST:
    """Lightweight offline stub used when API credentials are absent."""

    def __init__(self):
        self._price = float(os.getenv("DUMMY_BINANCE_PRICE", "20000"))

    async def account_snapshot(self):
        return {
            "balances": [{"asset": "USDT", "free": 1000.0, "locked": 0.0}],
            "positions": [],
        }

    async def submit_market_quote(self, symbol: str, side: str, quote: float):
        qty = float(quote) / self._price if self._price else float(quote)
        return {
            "symbol": symbol,
            "executedQty": qty,
            "filled_qty_base": qty,
            "avg_fill_price": self._price,
            "status": "FILLED",
        }

    async def submit_market_order(self, symbol: str, side: str, quantity: float):
        qty = float(quantity)
        return {
            "symbol": symbol,
            "executedQty": qty,
            "filled_qty_base": qty,
            "avg_fill_price": self._price,
            "status": "FILLED",
        }

    def get_last_price(self, symbol: str):
        return self._price

    def ticker_price(self, symbol: str):
        return {"price": self._price}

    def my_trades_since(self, symbol: str, start_ms: int):
        return []


if VENUE == "BINANCE" and (not settings.api_key or not settings.api_secret):
    rest_client = _DummyBinanceREST()
else:
    rest_client = BinanceREST()
portfolio = Portfolio()
router = OrderRouterExt(rest_client, portfolio)
startup_lock = asyncio.Lock()
_refresh_logger = logging.getLogger("engine.refresh")

# Attach metrics router
app.include_router(metrics.router)
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
try:
    metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
except Exception:
    pass
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)


# Attach strategy router only for trading role
if not IS_EXPORTER:
    app.include_router(strategy.router)


def _config_hash() -> str:
    """Generate stable hash of key config for provenance tracking."""
    keys = [
        "TRADING_ENABLED", "MIN_NOTIONAL_USDT", "MAX_NOTIONAL_USDT", "MAX_ORDERS_PER_MIN",
        "TRADE_SYMBOLS", "DUST_THRESHOLD_USD",
        "EXPOSURE_CAP_SYMBOL_USD", "EXPOSURE_CAP_TOTAL_USD",
        "VENUE_ERROR_BREAKER_PCT", "VENUE_ERROR_WINDOW_SEC",
    ]
    import os
    blob = "|".join(f"{k}={os.getenv(k, '')}" for k in keys)
    import hashlib
    return hashlib.sha1(blob.encode()).hexdigest()[:12]

@app.get("/readyz")
def readyz():
    """Lightweight readiness probe with only in-process checks."""
    try:
        snap_ok = bool(getattr(router, "snapshot_loaded", False))
    except Exception:
        snap_ok = False
    return {"ok": True, "snapshot_loaded": snap_ok, "mode": settings.mode}


@app.get("/version")
def version():
    """Return build provenance and model info."""
    import os
    return {
        "git_sha": os.getenv("GIT_SHA", "dev"),
        "model_tag": os.getenv("MODEL_TAG", "hmm_v1"),
        "config_hash": _config_hash(),
        "build_at": os.getenv("BUILD_AT", ""),
    }

_store = SnapshotStore()
_boot_status = {"snapshot_loaded": False, "reconciled": False}
_last_reconcile_ts = 0.0  # Track reconcile freshness
_last_specs_refresh = 0.0  # Track venue specs freshness
_basis_cache = {}  # {symbol: {entry_price, position_amt, last_sync_epoch}}
# Track last symbols we emitted per-symbol metrics for cleanup when positions close
_last_position_symbols: set[str] = set()
_price_map = {}  # symbol -> markPrice
_snapshot_counter = 0


class MarketOrderRequest(BaseModel):
    """Market order request. Exactly one of {quantity, quote} must be provided."""
    model_config = ConfigDict(extra="forbid")  # reject unexpected fields

    symbol: str = Field(..., description="e.g., BTCUSDT.BINANCE")
    side: Literal["BUY", "SELL"]
    quote: Optional[float] = Field(None, gt=0, description="Quote currency amount (USDT).")
    quantity: Optional[float] = Field(None, gt=0, description="Base asset quantity.")

    @model_validator(mode="after")
    def validate_exclusive(self):
        if (self.quantity is None) == (self.quote is None):
            raise ValueError("Set exactly one of quote or quantity.")
        return self


class LimitOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., description="e.g., BTCUSDT.BINANCE")
    side: Literal["BUY", "SELL"]
    price: float = Field(..., gt=0, description="Limit price")
    timeInForce: Literal["IOC", "FOK", "GTC"] = Field("IOC")
    quote: Optional[float] = Field(None, gt=0, description="Quote currency amount (USDT).")
    quantity: Optional[float] = Field(None, gt=0, description="Base asset quantity.")

    @model_validator(mode="after")
    def validate_exclusive(self):
        if (self.quantity is None) == (self.quote is None):
            raise ValueError("Set exactly one of quote or quantity.")
        return self


@app.on_event("startup")
async def on_startup() -> None:
    async with startup_lock:
        await router.initialize_balances()
        # Optional: seed starting cash for demo/test if no balances detected
        try:
            import os
            state = portfolio.state
            if (state.cash is None or state.cash <= 0):
                seed = os.getenv("STARTING_CASH_USD") or os.getenv("ENGINE_STARTING_CASH_USD")
                if seed is not None:
                    val = float(seed)
                    if val > 0:
                        state.cash = val
                        state.equity = val
        except Exception:
            pass
        # Initialize portfolio metrics
        state = portfolio.state
        metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)

        metrics.reset_core_metrics()


async def _refresh_specs_periodically():
    """Background task to refresh venue specs daily."""
    import datetime
    import logging
    logging.getLogger().info("Starting venue specs refresh background task")
    while True:
        try:
            from engine.core import venue_specs_loader
            venue_specs_loader.refresh()
            global _last_specs_refresh
            _last_specs_refresh = time.time()
            # Update metric
            if hasattr(metrics, 'REGISTRY') and 'last_specs_refresh_epoch' in metrics.REGISTRY:
                metrics.REGISTRY['last_specs_refresh_epoch'].set(_last_specs_refresh)
            logging.getLogger().info(f"Venue specs refreshed at {datetime.datetime.utcfromtimestamp(_last_specs_refresh)}")
        except Exception as e:
            logging.getLogger().error(f"Spec refresh failed: {e}")
        await asyncio.sleep(86400)  # 24h


@app.on_event("startup")
async def _start_specs_refresh():
    """Start the background venue specs refresh task."""
    asyncio.create_task(_refresh_specs_periodically())


@app.on_event("startup")
async def _init_multi_venue_clients():
    """Initialize and register multi-venue exchange clients."""
    if IS_EXPORTER:
        return
    try:
        from engine.connectors.ibkr_client import IbkrClient
        import os
        # Only initialize IBKR if connection details are provided
        if os.getenv("IBKR_HOST"):
            ibkr_client = IbkrClient()
            set_exchange_client("IBKR", ibkr_client)
            print("IBKR client initialized and registered")
    except ImportError:
        print("[WARN] IBKR client not available - ib-insync not installed")
    except Exception as e:
        print(f"[WARN] IBKR client initialization failed: {e}")


@app.on_event("startup")
async def _start_reconciliation():
    """Start the order state reconciliation daemon."""
    try:
        from engine.core.reconcile_daemon import reconcile_loop
        asyncio.create_task(reconcile_loop())
        print("[SYNC] Reconciliation daemon started")
    except ImportError:
        print("[WARN] Reconciliation module not available")
    except Exception as e:
        print(f"[WARN] Reconciliation daemon startup failed: {e}")


@app.post("/reconcile/manual")
async def manual_reconciliation():
    """Trigger a manual reconciliation run."""
    try:
        from engine.core.reconcile_daemon import reconcile_once
        stats = await reconcile_once()
        return {"status": "completed", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual reconciliation failed: {e}")


# Startup restoration: load snapshot and best-effort reconcile
def _startup_load_snapshot_and_reconcile():
    # 1) Load prior snapshot (if present) so UI has immediate state
    if _store.load():
        _boot_status["snapshot_loaded"] = True
    # 2) Best-effort reconcile to catch up with missed fills
    try:
        post_reconcile()  # same logic; small universe should be fast
    except Exception:
        # Non-fatal — engine can still serve, UI can trigger /reconcile manually
        pass
    # 3) Start strategy scheduler if enabled
    try:
        strategy.start_scheduler()
    except Exception:
        pass
    return True


# Run extra startup restoration after startup event
_startup_load_snapshot_and_reconcile()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await rest_client.close()


@app.post("/orders/market")
async def submit_market_order(req: MarketOrderRequest, request: Request):
    # Idempotency check
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        cached = CACHE.get(idem_key)
        if cached:
            return JSONResponse(content=cached, status_code=200)

    ok, err = RAILS.check_order(
        symbol=req.symbol,
        side=req.side,  # type: ignore
        quote=req.quote,
        quantity=req.quantity,
    )
    if not ok:
        metrics.orders_rejected.inc()
        status = 403 if err.get("error") in {"TRADING_DISABLED", "SYMBOL_NOT_ALLOWED"} else 400
        # Publish risk rejection event
        await publish_risk_event("rejected", {
            "symbol": req.symbol,
            "side": req.side,
            "quote": req.quote,
            "quantity": req.quantity,
            "reason": err.get("error", "UNKNOWN_RISK_VIOLATION"),
            "timestamp": time.time()
        })
        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

    # ——— Existing execution path (left intact) ———
    try:
        if req.quote is not None:
            result = await router.market_quote(req.symbol, req.side, req.quote)
        else:
            result = await router.market_quantity(req.symbol, req.side, req.quantity or 0.0)
        metrics.orders_submitted.inc()

        # Terminal status counters now increment in Portfolio.apply_fill();
        # additional venue statuses (canceled/expired) can be recorded by
        # reconciliation or explicit cancel flows.

        # Apply immediate fill to internal portfolio state (best-effort)
        try:
            sym = (result.get("symbol") or req.symbol).split(".")[0]
            qty_base = float(result.get("filled_qty_base") or 0.0)
            px = float(result.get("avg_fill_price") or 0.0)
            fee_usd = float(result.get("fee_usd") or 0.0)
            if qty_base > 0 and px > 0:
                portfolio.apply_fill(symbol=sym, side=req.side, quantity=qty_base, price=px, fee_usd=fee_usd)
                # Update gauges after applying the fill
                state = portfolio.state
                metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)
                # Persist snapshot
                _store.save(state.snapshot())
        except Exception:
            # Non-fatal; reconcile daemon or manual /reconcile can catch up
            pass

        resp = {
            "status": "submitted",
            "order": result,
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        append_jsonl("orders.jsonl", resp)
        if idem_key:
            CACHE.set(idem_key, resp)
        return resp
    except Exception as exc:  # pylint: disable=broad-except
        metrics.orders_rejected.inc()
        # Surface Binance error payloads for easier debugging
        try:
            if isinstance(exc, _httpx.HTTPStatusError) and exc.response is not None:
                status = exc.response.status_code
                body = exc.response.text
                raise HTTPException(status_code=status, detail=f"Binance error: {body}") from exc
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/orders/limit")
async def submit_limit_order(req: LimitOrderRequest, request: Request):
    # Idempotency check
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        cached = CACHE.get(idem_key)
        if cached:
            return JSONResponse(content=cached, status_code=200)

    ok, err = RAILS.check_order(
        symbol=req.symbol,
        side=req.side,  # type: ignore
        quote=req.quote,
        quantity=req.quantity,
    )
    if not ok:
        metrics.orders_rejected.inc()
        status = 403 if err.get("error") in {"TRADING_DISABLED", "SYMBOL_NOT_ALLOWED"} else 400
        await publish_risk_event("rejected", {
            "symbol": req.symbol,
            "side": req.side,
            "quote": req.quote,
            "quantity": req.quantity,
            "reason": err.get("error", "UNKNOWN_RISK_VIOLATION"),
            "timestamp": time.time()
        })
        return JSONResponse(content={"status": "rejected", **err}, status_code=status)

    try:
        if req.quote is not None:
            result = await router.limit_quote(req.symbol, req.side, req.quote, req.price, req.timeInForce)
        else:
            result = await router.limit_quantity(req.symbol, req.side, req.quantity or 0.0, req.price, req.timeInForce)
        metrics.orders_submitted.inc()

        # Apply immediate fill (best-effort)
        try:
            sym = (result.get("symbol") or req.symbol).split(".")[0]
            qty_base = float(result.get("filled_qty_base") or 0.0)
            px = float(result.get("avg_fill_price") or 0.0)
            fee_usd = float(result.get("fee_usd") or 0.0)
            if qty_base > 0 and px > 0:
                portfolio.apply_fill(symbol=sym, side=req.side, quantity=qty_base, price=px, fee_usd=fee_usd)
                st = portfolio.state
                metrics.update_portfolio_gauges(st.cash, st.realized, st.unrealized, st.exposure)
                _store.save(st.snapshot())
        except Exception:
            pass

        resp = {
            "status": "submitted",
            "order": result,
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        append_jsonl("orders.jsonl", resp)
        if idem_key:
            CACHE.set(idem_key, resp)
        return resp
    except Exception as exc:
        metrics.orders_rejected.inc()
        try:
            if isinstance(exc, _httpx.HTTPStatusError) and exc.response is not None:
                status = exc.response.status_code
                body = exc.response.text
                raise HTTPException(status_code=status, detail=f"Binance error: {body}") from exc
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/symbol_info")
async def symbol_info(symbol: str):
    """Return live venue filters for a symbol (min_notional, step size, etc.).

    Accepts symbols with or without venue suffix (e.g., BTCUSDT or BTCUSDT.BINANCE).
    """
    try:
        clean = symbol.split(".")[0].upper()
        filt = await rest_client.exchange_filter(clean)
        return {
            "symbol": clean,
            "step_size": filt.step_size,
            "min_qty": filt.min_qty,
            "min_notional": filt.min_notional,
            "max_notional": filt.max_notional,
            "tick_size": getattr(filt, "tick_size", 0.0),
            "is_futures": settings.is_futures,  # Add mode indicator
        }
    except Exception as exc:
        # Add URL debug info for troubleshooting
        third_party="undefined"
        try:
            import httpx
            if isinstance(exc, httpx.HTTPStatusError):
                third_party = exc.response.url if hasattr(exc.response, 'url') else "no_url"
        except Exception:
            pass
        base_used = settings.api_base or "no_base"
        mode_info = f"mode={settings.mode}, is_futures={settings.is_futures}"
        raise HTTPException(status_code=400,
                             detail=f"symbol_info failed: {exc} ({mode_info}, base_url={base_used}, url_attempted={third_party})")


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    """Return order data from JSONL audit log."""
    path = Path("engine/logs/orders.jsonl")
    if not path.exists():
        raise HTTPException(status_code=404, detail="No orders logged yet")
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if str(rec.get("order", {}).get("id")) == order_id:
                return rec
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")


@app.get("/portfolio")
async def get_portfolio():
    """
    Fast read via router if available, else return last snapshot.
    """
    try:
        snap = router.portfolio_snapshot()
    except Exception:
        snap = _store.load()
        if not snap:
            raise HTTPException(status_code=404, detail="No portfolio available")
    # Ensure UI gets USDT-normalized exposure per-position and dust-hidden hint
    try:
        prices = await last_prices()
        dust = risk_cfg.dust_threshold_usd
        positions = snap.get("positions", [])
        for p in positions:
            base = p.get("symbol", "").split(".")[0]
            base = base if base.endswith(QUOTE_CCY) else f"{base}{QUOTE_CCY}"
            last = prices.get(base) or p.get("last_price_quote")
            qty = float(p.get("qty_base", 0.0))
            p["last_price_quote"] = last
            p["unrealized_usd"] = float(p.get("unrealized_usd", 0.0))  # keep if already computed
            p["value_usd"] = (qty * float(last)) if (last is not None) else 0.0
            p["is_dust"] = abs(p["value_usd"]) < dust
            # Also update internal portfolio marks so unrealized PnL tracks market
            try:
                if last is not None:
                    portfolio.update_price(base, float(last))
            except Exception:
                pass
        snap["quote_ccy"] = QUOTE_CCY
        snap["positions"] = positions
    except Exception:
        pass
    # Refresh engine metrics from latest snapshot so external scrapers see updated values
    try:
        state = portfolio.state
        # Start with current state values; override below for futures
        metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)

        if settings.is_futures:
            # Compute unrealized PnL directly from the latest futures snapshot
            # and accumulate across ALL open positions.
            try:
                snap2 = await router.get_account_snapshot()
                positions2 = snap2.get("positions", []) if isinstance(snap2, dict) else []
                total_unreal = 0.0
                g = metrics.REGISTRY.get("pnl_unrealized_symbol")
                for pp in positions2:
                    try:
                        qty = float(pp.get("positionAmt", 0) or 0)
                        if abs(qty) <= 0.0:
                            continue
                        sym = str(pp.get("symbol", ""))
                        # Prefer venue-provided unrealizedProfit for mark-based PnL
                        upnl = float(pp.get("unrealizedProfit", 0.0) or 0.0)
                        total_unreal += upnl
                        if g is not None and sym:
                            g.labels(symbol=sym).set(upnl)
                    except Exception:
                        continue
                # market_value_usd := total unrealized (not Σ qty*price) for linear futures
                metrics.set_core_metric("market_value_usd", total_unreal)
                # Pull wallet cash directly from the venue snapshot for futures
                cash = 0.0
                try:
                    cash = float(snap2.get("totalWalletBalance") or snap2.get("walletBalance") or 0.0)
                except Exception:
                    cash = float(getattr(state, "cash", 0.0) or 0.0)

                # Sync in-process portfolio cash so subsequent calls are consistent
                try:
                    portfolio.state.cash = cash
                except Exception:
                    pass

                # Update gauges using live cash + unrealized (venue truth)
                metrics.update_portfolio_gauges(cash, state.realized, total_unreal, state.exposure)
                try:
                    metrics.set_core_metric("cash_usd", cash)
                    metrics.set_core_metric("equity_usd", cash + total_unreal)
                    # Margin figures (if present on snapshot)
                    try:
                        init_m = float(snap2.get("totalInitialMargin", 0.0))
                        maint_m = float(snap2.get("totalMaintMargin", 0.0))
                        avail = float(snap2.get("availableBalance", snap2.get("maxWithdrawAmount", 0.0)))
                        metrics.set_core_metric("initial_margin_usd", init_m)
                        metrics.set_core_metric("maint_margin_usd", maint_m)
                        metrics.set_core_metric("available_usd", avail)
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                # Fallback: use in-process state (already set above)
                try:
                    metrics.set_core_metric("market_value_usd", state.unrealized)
                except Exception:
                    pass
        else:
            # Spot: signed market value = sum(qty * last)
            try:
                mv = sum(pos.quantity * pos.last_price for pos in state.positions.values())
                metrics.set_core_metric("market_value_usd", mv)
                # Per-symbol unrealized for invariants derived from in-process state
                g = metrics.REGISTRY.get("pnl_unrealized_symbol")
                if g is not None:
                    for pos in state.positions.values():
                        g.labels(symbol=pos.symbol).set(pos.upl)
            except Exception:
                pass
        # Record mark time for auditability - always set, even when no positions
        try:
            metrics.set_core_metric("mark_time_epoch", time.time())
        except Exception:
            pass
    except Exception:
        pass
    return snap


@app.get("/account_snapshot")
async def account_snapshot(force: bool = False):
    """
    Return account snapshot. If force=1, pull a fresh snapshot from the venue
    and update router cache + snapshot_loaded flag immediately.
    """
    snap = await (router.fetch_account_snapshot() if force else router.get_account_snapshot())
    try:
        router.snapshot_loaded = True
    except Exception:
        pass
    return snap


@app.post("/reconcile")
def post_reconcile():
    """
    Fetch fills since last snapshot and apply. Runs in the request thread for simplicity;
    you can move to background if reconciliation might be slow.
    """
    # Symbols: prefer TRADE_SYMBOLS allowlist; fallback to router universe
    symbols = (risk_cfg.trade_symbols or [])
    if not symbols:
        try:
            symbols = router.trade_symbols()  # EXPECTED: provide in router
        except Exception:
            symbols = []
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols configured for reconciliation")

    try:
        snap = reconcile_since_snapshot(
            portfolio=router.portfolio_service(),   # EXPECTED: provide in router
            client=router.exchange_client(),        # EXPECTED: provide in router
            symbols=[s if s.endswith("USDT") else f"{s}USDT" for s in symbols],
        )
        _boot_status["reconciled"] = True
        global _last_reconcile_ts
        _last_reconcile_ts = time.time()
        metrics.reconcile_lag_seconds.set(0.0)
        return {"status": "ok", "applied_snapshot_ts_ms": snap.get("ts_ms"), "equity": snap.get("equity_usd")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconcile failed: {e}")


@app.get("/health")
async def health():
    try:
        snap = _store.load() or {}
    except Exception:
        snap = {}
    lag = max(0.0, time.time() - _last_reconcile_ts) if _last_reconcile_ts else None
    if lag is not None:
        metrics.reconcile_lag_seconds.set(lag)
    # Update snapshot_loaded gauge for alerting - derive truth from router state
    snap_ok = bool(getattr(router, "snapshot_loaded", False))
    try:
        metrics.REGISTRY["snapshot_loaded"].set(1 if snap_ok else 0)
    except Exception:
        pass

    # Include symbols if unrestricted
    from engine.config import load_risk_config
    risk_cfg = load_risk_config()
    symbols = None
    if risk_cfg.trade_symbols is None:
        try:
            from engine.universe import configured_universe
            symbols = configured_universe()
        except Exception:
            pass

    return {
        "engine": "ok",
        "mode": settings.mode,
        "api_base": settings.api_base,  # Updated to show active base URL
        "trading_enabled": settings.trading_enabled,
        "last_snapshot_error": getattr(router, "last_snapshot_error", None),
        "snapshot_loaded": snap_ok,  # UPDATED: accurate from router state
        "reconciled": getattr(router, "reconciled", False),
        "equity": snap.get("equity_usd"),
        "pnl_unrealized": (snap.get("pnl") or {}).get("unrealized"),
        "quote_ccy": QUOTE_CCY,
        "reconcile_lag_seconds": lag,
        "symbols": symbols,
        "price_source": "mark_price/premiumIndex" if settings.is_futures else "last_price/ticker",
        "basis_source": "positionRisk" if settings.is_futures else "in_memory",
        "positions_tracked": len(_basis_cache),
        "symbols_universe": len(_price_map) if _price_map else None,
        "equity_source": "fapi/v2/account.totalMarginBalance",
        "upnl_source": "positionRisk.sum(unRealizedProfit)",
        "wallet_source": "fapi/v2/account.totalWalletBalance",
    }


@app.get("/universe")
def get_universe():
    """Return configured trading symbols in BASEQUOTE (no venue suffix)."""
    return {"symbols": configured_universe(), "quote_ccy": QUOTE_CCY}


@app.get("/prices")
async def get_prices():
    """Return last trade/mark prices for current universe."""
    return {"prices": await last_prices(), "ts": time.time(), "quote_ccy": QUOTE_CCY}

@app.post("/strategy/promote")
async def promote_strategy(request: Request):
    """Hot-swap to a new strategy model at runtime."""
    import os
    data = await request.json()
    tag = data.get("model_tag")
    if not tag:
        raise HTTPException(status_code=400, detail="model_tag required")

    # Update environment and global model tag
    global MODEL_TAG
    MODEL_TAG = tag
    os.environ["MODEL_TAG"] = tag

    # Optionally notify strategy layer to reload model
    try:
        if hasattr(strategy, 'reload_model'):
            await strategy.reload_model(tag)
    except AttributeError:
        pass  # Strategy layer doesn't support hot reload, that's ok

    return {"message": f"Strategy switched to {tag}", "model_tag": tag}


@app.get("/stream")
async def sse_stream():
    """Server-Sent Events endpoint for real-time engine updates."""
    async def event_generator():
        """Generate SSE events for live UI updates."""
        queue = asyncio.Queue()
        handlers = {}  # Keep references to prevent garbage collection

        def queue_event(topic: str, data: dict):
            queue.put_nowait((topic, data))

        # Subscribe to key event topics
        topics = ["order.submitted", "order.filled", "order.closed", "risk.rejected",
                 "metrics.update", "strategy.promoted", "reconcile.completed"]

        for topic in topics:
            handlers[topic] = lambda data, topic=topic: queue_event(topic, data)
            BUS.subscribe(topic, handlers[topic])

        try:
            while True:
                topic, data = await queue.get()
                # Format as SSE (Server-Sent Events)
                yield f"event: {topic}\ndata: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            # Unsubscribe when connection closes
            for topic, handler in handlers.items():
                BUS.unsubscribe(topic, handler)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.on_event("startup")
async def _start_event_bus():
    """Initialize the real-time event bus."""
    if IS_EXPORTER:
        return
    try:
        await initialize_event_bus()
        print("[BUS] Event bus started - system is now reactive!")
    except Exception as e:
        print(f"[WARN] Event bus startup failed: {e}")


@app.on_event("startup")
async def _start_alerting():
    """Initialize the real-time alerting system."""
    if IS_EXPORTER:
        return
    try:
        await alert_daemon.initialize_alerting()
        print("[ALERT] Alerting system started - system is now conscious!")
    except Exception as e:
        print(f"[WARN] Alerting startup failed: {e}")


@app.on_event("startup")
async def _start_governance():
    """Initialize the autonomous governance system - the final layer!"""
    if IS_EXPORTER:
        return
    try:
        from ops import governance_daemon
        await governance_daemon.initialize_governance()
        print("[GOV] 🧠 Autonomous Governance activated - system now has FREE WILL!")
    except Exception as e:
        print(f"[WARN] Governance startup failed: {e}")


@app.on_event("startup")
async def _subscribe_governance_hooks():
    """React to governance actions by hot-reloading risk rails."""
    if IS_EXPORTER:
        return
    async def _on_governance_action(_data: dict) -> None:
        # Governance mutated runtime env vars; reflect into risk rails config
        from engine.config import load_risk_config
    try:
        RAILS.cfg = load_risk_config()
        metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
        try:
            metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
        except Exception:
            pass
    except Exception:
        pass

    try:
        BUS.subscribe("governance.action", _on_governance_action)
    except Exception:
        pass


async def _refresh_venue_data():
    """Background task to refresh price map, basis cache, and account totals from venue."""
    global _price_map, _basis_cache, _snapshot_counter

    try:
        _refresh_logger.info("Starting venue refresh loop (pid=%s, venue=%s, futures=%s)", os.getpid(), VENUE, settings.is_futures)
    except Exception:
        pass

    while True:
        try:
            if VENUE == "BINANCE" and settings.is_futures:
                try:
                    _refresh_logger.debug("refresh tick")
                except Exception:
                    pass
                # Refresh mark prices (best-effort)
                try:
                    price_data = await rest_client.bulk_premium_index()
                    if price_data:
                        _price_map = price_data
                except Exception:
                    pass

                # Account totals for cash/equity/UPNL and margin figures
                try:
                    acc_data = await rest_client.account()
                except Exception:
                    acc_data = {}
                if acc_data:
                    try:
                        wallet = float(acc_data.get("totalWalletBalance", 0.0))
                        upnl = float(acc_data.get("totalUnrealizedProfit", 0.0))
                        equity = float(acc_data.get("totalMarginBalance", 0.0))
                    except Exception:
                        wallet = upnl = equity = 0.0

                    metrics.set_core_metric("cash_usd", wallet)
                    metrics.set_core_metric("equity_usd", equity)
                    metrics.set_core_metric("market_value_usd", upnl)

                    try:
                        init_m = float(acc_data.get("totalInitialMargin", 0.0))
                        maint_m = float(acc_data.get("totalMaintMargin", 0.0))
                        avail = float(acc_data.get("availableBalance", acc_data.get("maxWithdrawAmount", 0.0)))
                        metrics.set_core_metric("initial_margin_usd", init_m)
                        metrics.set_core_metric("maint_margin_usd", maint_m)
                        metrics.set_core_metric("available_usd", avail)
                    except Exception:
                        pass

                # Position risk for per-symbol stats + consistency on UPNL
                try:
                    pos_data = await rest_client.position_risk()
                except Exception:
                    pos_data = []
                pos_data = [p for p in pos_data if float(p.get("positionAmt", 0.0)) != 0.0]

                is_hedge = False
                try:
                    is_hedge = await rest_client.hedge_mode()
                except Exception:
                    is_hedge = False

                if is_hedge:
                    legs = [p for p in pos_data if p.get("positionSide") in ("LONG", "SHORT")]
                else:
                    legs = [p for p in pos_data if p.get("positionSide", "BOTH") == "BOTH"]

                if legs:
                    try:
                        upnl_total = sum(float(p.get("unRealizedProfit", 0.0)) for p in legs)
                        metrics.set_core_metric("market_value_usd", upnl_total)
                    except Exception:
                        pass

                current_symbols: set[str] = set()
                by_symbol: dict[str, dict[str, float]] = {}
                for p in pos_data:
                    sym = p.get("symbol", "")
                    if not sym:
                        continue
                    entry = float(p.get("entryPrice", 0.0) or 0.0)
                    amt = float(p.get("positionAmt", 0.0) or 0.0)
                    upnl_sym = float(p.get("unRealizedProfit", 0.0) or 0.0)
                    agg = by_symbol.setdefault(sym, {"amt": 0.0, "entry": 0.0, "upnl": 0.0})
                    agg["amt"] += amt
                    if entry and amt:
                        try:
                            weight = abs(amt)
                            agg["entry"] = (
                                agg.get("entry", 0.0) * abs(agg.get("amt", 0.0)) + entry * weight
                            ) / max(1e-9, abs(agg.get("amt", 0.0)) + weight)
                        except Exception:
                            agg["entry"] = entry or agg.get("entry", 0.0)
                    agg["upnl"] += upnl_sym

                for sym, agg in by_symbol.items():
                    if agg.get("amt", 0.0) == 0.0:
                        continue
                    current_symbols.add(sym)
                    _basis_cache[sym] = {
                        "entry_price": float(agg.get("entry", 0.0)),
                        "position_amt": float(agg.get("amt", 0.0)),
                        "last_sync_epoch": time.time(),
                    }
                    try:
                        metrics.set_core_symbol_metric("position_amt", symbol=sym, value=float(agg.get("amt", 0.0)))
                        metrics.set_core_symbol_metric("entry_price", symbol=sym, value=float(agg.get("entry", 0.0)))
                        metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=float(agg.get("upnl", 0.0)))
                        mark = 0.0
                        try:
                            mark = float(_price_map.get(sym, 0.0)) if isinstance(_price_map, dict) else 0.0
                        except Exception:
                            mark = 0.0
                        if mark:
                            metrics.set_core_symbol_metric("mark_price", symbol=sym, value=mark)
                    except Exception:
                        pass

                try:
                    stale = _last_position_symbols - current_symbols
                    for sym in stale:
                        metrics.set_core_symbol_metric("position_amt", symbol=sym, value=0.0)
                        metrics.set_core_symbol_metric("unrealized_profit", symbol=sym, value=0.0)
                        metrics.set_core_symbol_metric("entry_price", symbol=sym, value=0.0)
                    _last_position_symbols.clear()
                    _last_position_symbols.update(current_symbols)
                except Exception:
                    pass

                now_ts = time.time()
                metrics.set_core_metric("mark_time_epoch", now_ts)
                metrics.set_core_metric("metrics_heartbeat", now_ts)
                _snapshot_counter += 1
                metrics.set_core_metric("snapshot_id", _snapshot_counter)

        except Exception:
            try:
                _refresh_logger.exception("refresh loop error")
            except Exception:
                pass
            pass

        await asyncio.sleep(5)


@app.on_event("startup")
async def _start_venue_refresh():
    """Start background venue data refresh."""
    # Avoid cross-polluting IBKR metrics by not running Binance refresh loop
    if VENUE == "BINANCE" and IS_EXPORTER:
        base_url = settings.api_base or "default"
        _refresh_logger.info(
            "Starting background refresh task venue=%s mode=%s base=%s pid=%s",
            VENUE,
            settings.mode,
            base_url,
            os.getpid(),
        )
        asyncio.create_task(_refresh_venue_data())


@app.on_event("startup")
def _init_prom_multiproc_dir():
    """Ensure PROMETHEUS_MULTIPROC_DIR exists and clear stale DBs on each worker boot."""
    try:
        import os
        import pathlib

        mp = os.getenv("PROMETHEUS_MULTIPROC_DIR", "/tmp/prom_multiproc")
        path = pathlib.Path(mp)
        path.mkdir(parents=True, exist_ok=True)

        for f in path.glob("*.db"):
            try:
                f.unlink()
            except FileNotFoundError:
                continue
            except Exception:
                pass
    except Exception:
        pass


@app.get("/events/stats")
def get_event_stats():
    """Get event bus statistics."""
    return {"event_bus": BUS.get_stats() if hasattr(BUS, 'get_stats') else {}}


@app.get("/alerts/stats")
def get_alert_stats():
    """Get alerting system statistics."""
    return {"alerting": alert_daemon._alert_daemon.get_stats() if alert_daemon._alert_daemon else {}}


@app.get("/risk/config")
def get_risk_config():
    """Return current risk rails configuration (live values)."""
    cfg = RAILS.cfg
    return {
        "trading_enabled": cfg.trading_enabled,
        "min_notional_usdt": cfg.min_notional_usdt,
        "max_notional_usdt": cfg.max_notional_usdt,
        "max_orders_per_min": cfg.max_orders_per_min,
        "exposure_cap_symbol_usd": cfg.exposure_cap_symbol_usd,
        "exposure_cap_total_usd": cfg.exposure_cap_total_usd,
        "venue_error_breaker_pct": cfg.venue_error_breaker_pct,
        "venue_error_window_sec": cfg.venue_error_window_sec,
    }


@app.post("/risk/reload")
def reload_risk_config():
    """Hot-reload risk configuration from environment variables."""
    from engine.config import load_risk_config
    RAILS.cfg = load_risk_config()
    metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
    try:
        metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
    except Exception:
        pass
    cfg = RAILS.cfg
    return {
        "status": "ok",
        "trading_enabled": cfg.trading_enabled,
        "min_notional_usdt": cfg.min_notional_usdt,
        "max_notional_usdt": cfg.max_notional_usdt,
        "max_orders_per_min": cfg.max_orders_per_min,
    }


@app.get("/governance/status")
def get_governance_status():
    """Get autonomous governance system status."""
    try:
        from ops import governance_daemon
        return {"governance": governance_daemon.get_governance_status()}
    except Exception as e:
        return {"governance": {"status": "error", "error": str(e)}}


@app.post("/governance/reload")
def reload_governance_policies():
    """Hot-reload governance policies."""
    try:
        from ops import governance_daemon
        success = governance_daemon.reload_governance_policies()
        return {"status": "success" if success else "failed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/governance/actions")
def list_governance_actions(limit: int = 20):
    """Return the most recent governance actions (audit log)."""
    try:
        from ops import governance_daemon
        actions = governance_daemon.get_recent_governance_actions(limit)
        return {"actions": actions, "limit": limit}
    except Exception as e:
        return {"actions": [], "error": str(e)}


@app.post("/governance/simulate/{event_type}")
async def simulate_governance_event(event_type: str):
    """Simulate governance triggers for testing."""
    # Simulate different types of events that would trigger governance
    test_events = {
        "poor_performance": {
            "pnl_unrealized": -150.0,
            "sharpe": 0.05,
            "equity_usd": 9850.0
        },
        "great_performance": {
            "pnl_unrealized": 120.0,
            "sharpe": 2.5,
            "equity_usd": 10120.0
        },
        "risk_breach": {
            "symbol": "BTCUSDT.BINANCE",
            "side": "BUY",
            "reason": "EXPOSURE_LIMIT"
        },
        "market_stress": {
            "spread_pct": 0.03,
            "volatility_spike": True
        }
    }

    if event_type in test_events:
        try:
            # Publish test event to trigger governance
            if event_type == "poor_performance":
                await BUS.publish("metrics.update", test_events[event_type])
            elif event_type == "great_performance":
                await BUS.publish("metrics.update", test_events[event_type])
            elif event_type == "risk_breach":
                await BUS.publish("risk.rejected", test_events[event_type])
            elif event_type == "market_stress":
                await BUS.publish("price.anomaly", test_events[event_type])

            return {"status": f"simulated {event_type}", "data": test_events[event_type]}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        return {"status": "error", "message": f"Unknown event type: {event_type}"}
