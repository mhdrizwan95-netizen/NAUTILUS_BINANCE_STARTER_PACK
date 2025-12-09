"""
Nautilus Ops API - Gateway to Engine Services

This module provides a facade API that proxies requests to the engine
and aggregates data for the frontend dashboard.
"""
from fastapi import FastAPI, Response, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
import os
import httpx
import asyncio
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ops.api")

APP = FastAPI(title="Nautilus Ops", version="0.2.0")

# Engine connection settings
ENGINE_URL = os.getenv("ENGINE_URL", "http://engine_binance:8003").rstrip("/")
ENGINE_TIMEOUT = float(os.getenv("ENGINE_TIMEOUT", "5.0"))

# Shared async client for connection pooling
_http_client: httpx.AsyncClient | None = None

async def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=ENGINE_TIMEOUT)
    return _http_client

@APP.on_event("shutdown")
async def shutdown_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()

# CORS
APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Health & Status Endpoints - Proxy to Engine
# ============================================================================

@APP.get("/health")
@APP.get("/readyz")
@APP.get("/livez")
@APP.get("/api/health")
async def health_check():
    """Fetch real health status from engine."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/health")
        if resp.status_code == 200:
            data = resp.json()
            # Transform to frontend expected format
            return {
                "status": "ok" if data.get("status") == "ok" else "degraded",
                "venues": data.get("venues", [
                    {"name": "Binance", "status": "ok", "latencyMs": 50, "queue": 0}
                ])
            }
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(f"Engine health check failed: {e}")
    
    # Fallback: check if engine is reachable at all
    try:
        start = time.time()
        resp = await client.get(f"{ENGINE_URL}/metrics/prometheus", timeout=2.0)
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": "ok",
            "venues": [
                {"name": "Binance", "status": "ok", "latencyMs": latency_ms, "queue": 0}
            ]
        }
    except Exception:
        return {
            "status": "degraded",
            "venues": [
                {"name": "Binance", "status": "down", "latencyMs": 0, "queue": 0}
            ]
        }

@APP.post("/api/ops/ws-session")
async def issue_ws_session():
    """Issue a WebSocket session token for frontend."""
    # Generate a simple session token (in production, this should be JWT-signed)
    import secrets
    token = secrets.token_urlsafe(32)
    return {"session": token, "expires": 3600}


# ============================================================================
# Event Ingestion Endpoints - Receive events from Engine
# ============================================================================

# In-memory price cache (last N ticks per symbol)
_price_cache: dict[str, list[dict]] = {}
_PRICE_CACHE_SIZE = 100

@APP.post("/api/events/price")
async def receive_price_event(request: Request):
    """
    Receive price tick events from the engine's PriceBridge.
    Stores ticks in memory for dashboard/charting use.
    """
    try:
        tick = await request.json()
        symbol = tick.get("symbol")
        if not symbol:
            return {"status": "ignored", "reason": "no symbol"}
        
        # Store in cache
        if symbol not in _price_cache:
            _price_cache[symbol] = []
        
        _price_cache[symbol].append({
            "price": tick.get("price"),
            "ts": tick.get("ts", time.time()),
            "source": tick.get("source"),
        })
        
        # Trim to max size
        if len(_price_cache[symbol]) > _PRICE_CACHE_SIZE:
            _price_cache[symbol] = _price_cache[symbol][-_PRICE_CACHE_SIZE:]
        
        return {"status": "ok"}
    except Exception as e:
        logger.warning(f"Failed to process price event: {e}")
        return {"status": "error", "error": str(e)}


@APP.get("/api/events/prices")
async def get_price_events(symbol: str | None = None, limit: int = 50):
    """
    Get cached price events for charting.
    """
    if symbol:
        ticks = _price_cache.get(symbol, [])[-limit:]
        return {"symbol": symbol, "ticks": ticks}
    
    # Return summary of all symbols
    summary = {}
    for sym, ticks in _price_cache.items():
        if ticks:
            summary[sym] = {
                "latest": ticks[-1],
                "count": len(ticks)
            }
    return {"symbols": summary}

@APP.get("/status")
async def get_status():
    """Fetch trading status from engine."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/status")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(f"Engine status check failed: {e}")
    
    # Fallback
    return {"ok": True, "state": {"trading_enabled": False}}

@APP.get("/api/config/effective")
async def get_config_effective():
    """Fetch effective config from engine."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/config")
        if resp.status_code == 200:
            data = resp.json()
            return {"effective": data}
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(f"Engine config fetch failed: {e}")
    
    # Fallback with reasonable defaults
    dry_run = os.getenv("DRY_RUN", "true").lower() in {"true", "1", "yes"}
    trading_enabled = os.getenv("TRADING_ENABLED", "false").lower() in {"true", "1", "yes"}
    return {
        "effective": {
            "global": {"trading_enabled": trading_enabled},
            "strategies": {},
            "risk": {},
            "DRY_RUN": dry_run
        }
    }

@APP.get("/api/metrics/summary")
async def get_metrics_summary():
    """Fetch portfolio metrics summary from engine."""
    client = await get_client()
    try:
        # Fetch aggregate data
        portfolio_resp = await client.get(f"{ENGINE_URL}/aggregate/portfolio")
        pnl_resp = await client.get(f"{ENGINE_URL}/aggregate/pnl")
        stats_resp = await client.get(f"{ENGINE_URL}/trades/stats")
        
        portfolio = portfolio_resp.json() if portfolio_resp.status_code == 200 else {}
        pnl = pnl_resp.json() if pnl_resp.status_code == 200 else {}
        stats = stats_resp.json() if stats_resp.status_code == 200 else {}
        
        # Calculate KPIs from real data
        realized = pnl.get("realized", {})
        unrealized = pnl.get("unrealized", {})
        
        total_pnl = sum(realized.values()) + sum(unrealized.values())
        positions_count = len([v for v in unrealized.values() if v != 0])
        
        # Get computed stats from engine
        win_rate = float(stats.get("win_rate", 0.0))
        sharpe = float(stats.get("sharpe", 0.0))
        max_drawdown = float(stats.get("max_drawdown", 0.0))
        returns = stats.get("returns", [])
        
        # Build PnL by symbol
        pnl_by_symbol = []
        for symbol, val in {**realized, **unrealized}.items():
            pnl_by_symbol.append({"symbol": symbol, "pnl": val})
        
        return {
            "kpis": {
                "totalPnl": total_pnl,
                "winRate": win_rate,
                "sharpe": sharpe,
                "maxDrawdown": max_drawdown,
                "openPositions": positions_count
            },
            "equityByStrategy": [],
            "pnlBySymbol": pnl_by_symbol[:10],  # Top 10
            "returns": returns
        }
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(f"Engine metrics fetch failed: {e}")
    
    # Fallback with zeros
    return {
        "kpis": {
            "totalPnl": 0.0,
            "winRate": 0.0,
            "sharpe": 0.0,
            "maxDrawdown": 0.0,
            "openPositions": 0
        },
        "equityByStrategy": [],
        "pnlBySymbol": [],
        "returns": []
    }

# ============================================================================
# Proxy endpoints for frontend API calls
# ============================================================================

@APP.post("/api/strategies/{strategy_id}/start")
async def start_strategy(strategy_id: str, request: Request):
    """Proxy to engine for starting a strategy."""
    client = await get_client()
    try:
        # Forward the request to the engine
        # We need to forward headers for auth (X-Ops-Token)
        headers = dict(request.headers)
        headers.pop("content-length", None) # Let httpx handle content-length
        headers.pop("host", None)
        
        resp = await client.post(f"{ENGINE_URL}/strategies/{strategy_id}/start", headers=headers)
        if resp.status_code == 200:
            return resp.json()
        else:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.error(f"Engine strategy start failed: {e}")
        raise HTTPException(status_code=503, detail="Engine unavailable")

@APP.post("/api/strategies/{strategy_id}/stop")
async def stop_strategy(strategy_id: str, request: Request):
    """Proxy to engine for stopping a strategy."""
    client = await get_client()
    try:
        headers = dict(request.headers)
        headers.pop("content-length", None)
        headers.pop("host", None)
        
        resp = await client.post(f"{ENGINE_URL}/strategies/{strategy_id}/stop", headers=headers)
        if resp.status_code == 200:
            return resp.json()
        else:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.error(f"Engine strategy stop failed: {e}")
        raise HTTPException(status_code=503, detail="Engine unavailable")

@APP.post("/api/strategies/{strategy_id}/update")
async def update_strategy(strategy_id: str, request: Request):
    """Proxy to engine for updating a strategy."""
    client = await get_client()
    try:
        body = await request.json()
        headers = dict(request.headers)
        headers.pop("content-length", None)
        headers.pop("host", None)
        
        resp = await client.post(f"{ENGINE_URL}/strategies/{strategy_id}/update", json=body, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        else:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.error(f"Engine strategy update failed: {e}")
        raise HTTPException(status_code=503, detail="Engine unavailable")

@APP.post("/api/ops/flatten")
async def flatten_positions(request: Request):
    """Proxy to engine for flattening positions."""
    client = await get_client()
    try:
        body = await request.json()
        headers = dict(request.headers)
        headers.pop("content-length", None)
        headers.pop("host", None)
        
        resp = await client.post(f"{ENGINE_URL}/ops/flatten", json=body, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        else:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.error(f"Engine flatten failed: {e}")
        raise HTTPException(status_code=503, detail="Engine unavailable")

@APP.get("/api/strategies")
async def get_strategies():
    """Proxy to engine for strategy list."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/strategies")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"data": [], "page": {"nextCursor": None, "prevCursor": None, "limit": 50}}

@APP.get("/api/positions")
async def get_positions():
    """Proxy to engine for positions."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/aggregate/exposure")
        if resp.status_code == 200:
            data = resp.json()
            positions = []
            by_symbol = data.get("by_symbol", {})
            for symbol, entry in by_symbol.items():
                positions.append({
                    "symbol": symbol,
                    "qty": entry.get("qty_base", 0),
                    "entry": 0,  # Would need from portfolio
                    "mark": entry.get("last_price_usd", 0),
                    "pnl": 0
                })
            return {"data": positions, "page": {"nextCursor": None, "prevCursor": None, "limit": 100}}
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"data": [], "page": {"nextCursor": None, "prevCursor": None, "limit": 100}}

@APP.get("/api/trades/recent")
async def get_recent_trades():
    """Proxy to engine for recent trades."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/trades/recent")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"data": [], "page": {"nextCursor": None, "prevCursor": None, "limit": 100}}

@APP.get("/api/alerts")
async def get_alerts():
    """Proxy to engine for alerts."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/alerts")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"data": [], "page": {"nextCursor": None, "prevCursor": None, "limit": 50}}

@APP.get("/api/orders/open")
async def get_open_orders():
    """Proxy to engine for open orders."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/orders/open")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"data": [], "page": {"nextCursor": None, "prevCursor": None, "limit": 100}}

@APP.get("/aggregate/portfolio")
async def get_aggregate_portfolio():
    """Proxy to engine for aggregate portfolio."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/aggregate/portfolio")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {
        "equity_usd": 0,
        "cash_usd": 0,
        "gain_usd": 0,
        "return_pct": 0,
        "baseline_equity_usd": 0
    }

@APP.get("/aggregate/exposure")
async def get_aggregate_exposure():
    """Proxy to engine for aggregate exposure."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/aggregate/exposure")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"totals": {"exposure_usd": 0, "count": 0, "venues": 0}, "by_symbol": {}}

@APP.get("/aggregate/pnl")
async def get_aggregate_pnl():
    """Proxy to engine for aggregate PnL."""
    client = await get_client()
    try:
        resp = await client.get(f"{ENGINE_URL}/aggregate/pnl")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return {"realized": {}, "unrealized": {}}

# ============================================================================
# UI Serving Logic
# ============================================================================

candidate_paths = [
    "/app/frontend/dist",
    "frontend/dist",
    "/app/ops/static_ui",
    "static_ui",
    "/app/frontend/build"
]

static_dir = None
for path in candidate_paths:
    if os.path.exists(path) and os.path.isdir(path):
        static_dir = path
        break

if static_dir:
    print(f"INFO: Serving static UI from {static_dir}")
    # 1. Mount Static Assets (JS/CSS)
    assets_path = os.path.join(static_dir, "assets")
    if os.path.exists(assets_path):
        APP.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    
    # 2. Serve Index.html (SPA Catch-All)
    @APP.get("/{full_path:path}")
    async def serve_app(full_path: str):
        # Allow API routes to pass through
        if full_path.startswith("api") or full_path.startswith("ws") or full_path.startswith("status") or full_path.startswith("aggregate"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse({"detail": "Index not found"}, status_code=404)
else:
    print(f"⚠️ WARNING: Frontend build not found in {candidate_paths}")
    @APP.get("/")
    async def root():
        return JSONResponse({"detail": "Frontend not found. Please run npm run build."}, status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(APP, host="0.0.0.0", port=8002)
