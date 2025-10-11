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

from engine.config import get_settings, load_risk_config, QUOTE_CCY
from engine.core.binance import BinanceREST
from engine.core.order_router import OrderRouter, set_exchange_client
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
router = OrderRouter(rest_client, portfolio)
startup_lock = asyncio.Lock()

# Attach metrics router
app.include_router(metrics.router)


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


@app.on_event("startup")
async def on_startup() -> None:
    async with startup_lock:
        await router.initialize_balances()
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

        resp = {
            "status": "submitted",
            "order": result,
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        append_jsonl("orders.jsonl", resp)
        if idem_key:
            CACHE.set(idem_key, resp)
        # Persist a fresh portfolio snapshot after submission path returns success from router
        try:
            snap = portfolio.state.snapshot()
            _store.save(snap)
        except Exception:
            pass
        return resp
    except Exception as exc:  # pylint: disable=broad-except
        metrics.orders_rejected.inc()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        snap["quote_ccy"] = QUOTE_CCY
        snap["positions"] = positions
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
    return {
        "engine": "ok",
        "mode": settings.mode,
        "trading_enabled": settings.trading_enabled,
        "snapshot_loaded": _boot_status["snapshot_loaded"],
        "reconciled": _boot_status["reconciled"],
        "equity": snap.get("equity_usd"),
        "pnl_unrealized": (snap.get("pnl") or {}).get("unrealized"),
        "quote_ccy": QUOTE_CCY,
        "reconcile_lag_seconds": lag,
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


@app.get("/events/stats")
def get_event_stats():
    """Get event bus statistics."""
    return {"event_bus": BUS.get_stats() if hasattr(BUS, 'get_stats') else {}}


@app.get("/alerts/stats")
def get_alert_stats():
    """Get alerting system statistics."""
    return {"alerting": alert_daemon._alert_daemon.get_stats() if alert_daemon._alert_daemon else {}}


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
