from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
import os

APP = FastAPI(title="Nautilus Ops", version="0.1.0")

# CORS
APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Endpoints (Legacy Support)
@APP.get("/health")
@APP.get("/readyz")
@APP.get("/livez")
@APP.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "venues": [
            {"name": "Binance", "status": "ok", "latencyMs": 50, "queue": 0}
        ]
    }

@APP.post("/api/ops/ws-session")
async def issue_ws_session():
    # Return a dummy session token
    return {"session": "dummy_session_token", "expires": 3600}

@APP.get("/status")
async def get_status():
    return {"ok": True, "state": {"trading_enabled": False}}

@APP.get("/api/config/effective")
async def get_config_effective():
    return {
        "effective": {
            "global": {"trading_enabled": False},
            "strategies": {},
            "risk": {},
            "DRY_RUN": True
        }
    }

@APP.get("/api/metrics/summary")
async def get_metrics_summary():
    return {
        "kpis": {
            "totalPnl": 100.0,
            "winRate": 0.5,
            "sharpe": 1.5,
            "maxDrawdown": 0.1,
            "openPositions": 1
        },
        "equityByStrategy": [{"t": "2023-01-01T00:00:00Z", "strategy_demo": 1000.0}],
        "pnlBySymbol": [{"symbol": "BTCUSDT", "pnl": 10.0}],
        "returns": [0.01, 0.02, -0.01, 0.03]
    }

# UI Serving Logic
# We check multiple candidate locations for the frontend build.
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
        if full_path.startswith("api") or full_path.startswith("ws") or full_path.startswith("status"):
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
