from __future__ import annotations

import asyncio
import time
import json
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
import json
import httpx as _httpx

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
risk_cfg = load_risk_config()
RAILS = RiskRails(risk_cfg)
rest_client = BinanceREST()
portfolio = Portfolio()
router = OrderRouterExt(rest_client, portfolio)
startup_lock = asyncio.Lock()

# Attach metrics router
app.include_router(metrics.router)
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)
try:
    metrics.set_max_notional(RAILS.cfg.max_notional_usdt)
except Exception:
    pass
metrics.set_trading_enabled(RAILS.cfg.trading_enabled)


# Attach strategy router
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
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"symbol_info failed: {exc}")


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
        metrics.update_portfolio_gauges(state.cash, state.realized, state.unrealized, state.exposure)
        # Update signed market value (sum of qty*last)
        try:
            mv = sum(pos.quantity * pos.last_price for pos in state.positions.values())
            metrics.REGISTRY["market_value_usd"].set(mv)
        except Exception:
            pass
        # Update per-symbol unrealized gauges for invariants
        try:
            g = metrics.REGISTRY.get("pnl_unrealized_symbol")
            if g is not None:
                for pos in state.positions.values():
                    # Symbol names in snapshots include venue suffix; keep base symbol here
                    g.labels(symbol=pos.symbol).set(pos.upl)
        except Exception:
            pass
        # Record mark time for auditability - always set, even when no positions
        try:
            metrics.REGISTRY["mark_time_epoch"].set(time.time())
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
        "spot_base": getattr(settings, "base_url", None),
        "trading_enabled": settings.trading_enabled,
        "last_snapshot_error": getattr(router, "last_snapshot_error", None),
        "snapshot_loaded": snap_ok,  # UPDATED: accurate from router state
        "reconciled": getattr(router, "reconciled", False),
        "equity": snap.get("equity_usd"),
        "pnl_unrealized": (snap.get("pnl") or {}).get("unrealized"),
        "quote_ccy": QUOTE_CCY,
        "reconcile_lag_seconds": lag,
        "symbols": symbols,
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
    try:
        await initialize_event_bus()
        print("[BUS] Event bus started - system is now reactive!")
    except Exception as e:
        print(f"[WARN] Event bus startup failed: {e}")


@app.on_event("startup")
async def _start_alerting():
    """Initialize the real-time alerting system."""
    try:
        await alert_daemon.initialize_alerting()
        print("[ALERT] Alerting system started - system is now conscious!")
    except Exception as e:
        print(f"[WARN] Alerting startup failed: {e}")


@app.on_event("startup")
async def _start_governance():
    """Initialize the autonomous governance system - the final layer!"""
    try:
        from ops import governance_daemon
        await governance_daemon.initialize_governance()
        print("[GOV] 🧠 Autonomous Governance activated - system now has FREE WILL!")
    except Exception as e:
        print(f"[WARN] Governance startup failed: {e}")


@app.on_event("startup")
async def _subscribe_governance_hooks():
    """React to governance actions by hot-reloading risk rails."""
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
