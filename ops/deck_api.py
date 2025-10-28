
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio, json, os
from typing import Dict, Any

app = FastAPI(title="Nautilus Deck API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE = {
    "mode": "yellow",
    "kill": False,
    "strategies": {
        "scalp":{"enabled": True,  "risk_share": 0.25},
        "momentum":{"enabled": True,"risk_share": 0.35},
        "trend":{"enabled": True,  "risk_share": 0.25},
        "event":{"enabled": True,  "risk_share": 0.15},
    },
    "universe_weights": {
        "liquidity":0.25,"volatility":0.20,"velocity":0.25,"spread":0.10,"funding":0.05,"event_heat":0.15
    },
    "metrics": {
        "equity_usd": 2000.0,
        "open_positions": 0,
        "open_risk_sum_pct": 0.0,
        "pnl_24h": 0.0,
        "drawdown_pct": 0.0,
        "tick_to_order_ms_p50": 50.0,
        "tick_to_order_ms_p95": 95.0,
        "venue_error_rate_pct": 0.0,
        "breaker": {"equity": False, "venue": False}
    },
    "top_symbols": [],
}

class ModeIn(BaseModel):
    mode: str

class ToggleIn(BaseModel):
    enabled: bool

class RiskShareIn(BaseModel):
    strategy: str
    risk_share: float

class UniverseWeightsIn(BaseModel):
    liquidity: float
    volatility: float
    velocity: float
    spread: float
    funding: float
    event_heat: float

@app.get("/status")
async def status():
    return JSONResponse(STATE)

CLIENTS = set()
async def broadcast(msg: Dict[str, Any]):
    data = json.dumps(msg)
    dead = []
    for ws in list(CLIENTS):
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for d in dead:
        CLIENTS.discard(d)

@app.post("/risk/mode")
async def set_mode(m: ModeIn):
    STATE["mode"] = m.mode
    await broadcast({"type":"mode", "mode": m.mode})
    return {"ok": True}

@app.post("/kill")
async def kill(t: ToggleIn):
    STATE["kill"] = t.enabled
    await broadcast({"type":"kill", "enabled": t.enabled})
    return {"ok": True}

@app.post("/allocator/weights")
async def set_weights(r: RiskShareIn):
    if r.strategy in STATE["strategies"]:
        STATE["strategies"][r.strategy]["risk_share"] = float(max(0.0, min(1.0, r.risk_share)))
        await broadcast({"type":"weights", "strategy": r.strategy, "risk_share": STATE["strategies"][r.strategy]["risk_share"]})
    return {"ok": True}

@app.post("/universe/weights")
async def set_universe(w: UniverseWeightsIn):
    STATE["universe_weights"] = w.model_dump()
    await broadcast({"type":"universe_weights", **STATE["universe_weights"]})
    return {"ok": True}

@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    CLIENTS.add(ws)
    await ws.send_text(json.dumps({"type":"snapshot", **STATE}))
    try:
        while True:
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        CLIENTS.discard(ws)

static_dir = os.environ.get("DECK_STATIC_DIR","./deck")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="deck")
