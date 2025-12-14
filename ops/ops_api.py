"""
Nautilus Ops API - Gateway to Engine Services

This module provides a facade API that proxies requests to the engine
and aggregates data for the frontend dashboard.
"""
import os
import time
import httpx
import logging
import asyncio
import secrets
import websockets
import aiofiles
from pathlib import Path
from fastapi import FastAPI, Response, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
try:
    from shared.logging import setup_logging
    setup_logging("ops_api")
except ImportError:
    # Fallback if shared volume not mounted yet
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("ops.api").warning("Shared logging module not found. Using default.")

logger = logging.getLogger("ops.api")

APP = FastAPI(title="Nautilus Ops", version="0.2.0")

# Engine connection settings
ENGINE_URL = os.getenv("ENGINE_URL", "http://engine_binance:8003").rstrip("/")
ENGINE_TIMEOUT = float(os.getenv("ENGINE_TIMEOUT", "5.0"))
HMM_URL = os.getenv("HMM_URL", "http://ml_service:8000").rstrip("/")


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
                "status": "ok" if (data.get("status") == "ok" or data.get("engine") == "ok") else "degraded",
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


@APP.get("/api/metrics/models")
async def get_metrics_models():
    """Proxy to ML service for model history."""
    try:
        client = await get_client()
        resp = await client.get(f"{HMM_URL}/models", timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"ML Service returned status {resp.status_code}")
    except Exception as e:
        logger.exception(f"Failed to fetch models: {e}")
    return {"data": [], "page": {"nextCursor": None, "prevCursor": None, "limit": 50}}


@APP.post("/api/ai/generate")
async def generate_ai_content(request: Request):
    """Proxy AI generation to Google Gemini (server-side)."""
    try:
        data = await request.json()
        prompt = data.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt is required")
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            # Check if we are in a dev environment with a hardcoded fallback (Discouraged but handling legacy)
            # For now, just error out securely
            raise HTTPException(status_code=503, detail="AI service not configured (Server missing GEMINI_API_KEY)")

        client = await get_client()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={api_key}"
        
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        resp = await client.post(url, json=payload, timeout=10.0)
        
        if resp.status_code != 200:
            logger.warning(f"Gemini API error: {resp.text}")
            raise HTTPException(status_code=resp.status_code, detail="AI Provider Error")
            
        return resp.json()
        
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI Provider Timeout")
    except Exception as e:
        logger.exception(f"AI Generation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@APP.get("/api/scanner/state")
async def get_scanner_state():
    """Read the latest Symbol Scanner state."""
    try:
        # Path is shared via volume mapping to /app/data
        path = "/app/data/runtime/symbol_scanner_state.json"
        
        # In dev mode, it might be relative
        if not os.path.exists(path):
            if os.path.exists("data/runtime/symbol_scanner_state.json"):
                path = "data/runtime/symbol_scanner_state.json"
        
        if not os.path.exists(path):
             return {"selected": [], "scores": {}}

        import aiofiles
        async with aiofiles.open(path, mode='r') as f:
            content = await f.read()
            return json.loads(content)
            
    except Exception as e:
        logger.warning(f"Failed to read scanner state: {e}")
        return {"selected": [], "scores": {}}


@APP.get("/api/logs")
async def get_logs(lines: int = Query(100, ge=1, le=2000), filter: str | None = None):
    """
    Retrieve the last N lines of the system log.
    Supports simple text filtering.
    """
    log_file = Path("/app/data/logs/system.jsonl")
    
    # Handle dev environment path difference
    if not log_file.exists():
        if os.path.exists("data/logs/system.jsonl"):
            log_file = Path("data/logs/system.jsonl")

    if not log_file.exists():
         return {"logs": []}
    
    try:
        async with aiofiles.open(log_file, mode='r') as f:
            # Efficiently read last N lines is tricky with async, 
            # but file is rotated at 10MB, so reading all lines in memory is acceptable for now (~1-2s max)
            content = await f.readlines()
            
            # Filter if requested
            if filter:
                filter_lower = filter.lower()
                content = [line for line in content if filter_lower in line.lower()]
                
            # Take last N
            selection = content[-lines:]
            
            # Parse JSON
            parsed_logs = []
            for line in selection:
                try:
                    parsed_logs.append(json.loads(line))
                except json.JSONDecodeError:
                    parsed_logs.append({"ts": "", "level": "RAW", "msg": line.strip(), "service": "unknown"})
            
            return {"logs": parsed_logs}
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        return {"logs": [], "error": str(e)}


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

@APP.websocket("/ws")
async def websocket_proxy(websocket: WebSocket):
    """Proxy WebSocket connections to the engine."""
    await websocket.accept()
    token = websocket.query_params.get("token", "")
    
    # Construct upstream URL (Engine)
    engine_ws_base = ENGINE_URL.replace("http://", "ws://").replace("https://", "wss://")
    upstream_url = f"{engine_ws_base}/ws?token={token}"
    
    try:
        async with websockets.connect(upstream_url) as upstream_ws:
            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await upstream_ws.send(data)
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.debug(f"WS client->upstream error: {e}")

            async def upstream_to_client():
                try:
                    async for message in upstream_ws:
                        await websocket.send_text(message)
                except Exception as e:
                    logger.debug(f"WS upstream->client error: {e}")

            # Run both readers concurrently
            await asyncio.gather(
                client_to_upstream(),
                upstream_to_client(),
                return_exceptions=True
            )
    except Exception as e:
        logger.error(f"WS proxy connection failed: {e}")
        # Close with policy violation or internal error
        try:
            await websocket.close(code=1011)
        except Exception:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(APP, host="0.0.0.0", port=8002)
