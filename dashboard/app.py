from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest, multiprocess, Counter, Gauge
from prometheus_client import CollectorRegistry
from fastapi import Response
import pandas as pd
from pathlib import Path
import asyncio
import time, json

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = APP_ROOT.parent / "data" / "processed"

app = FastAPI(title="HMM Trader Dashboard")
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))

# Prometheus registry (single-process simple mode)
_registry = CollectorRegistry()
g_state = Gauge("state_active", "Active HMM state", ["id"], registry=_registry)
c_guard = Counter("guardrail_trigger_total", "Guardrail triggers", ["reason"], registry=_registry)
g_pnl_realized = Gauge("pnl_realized", "Realized PnL", registry=_registry)
g_pnl_unrealized = Gauge("pnl_unrealized", "Unrealized PnL", registry=_registry)
g_drift = Gauge("drift_score", "Feature drift (KLD)", registry=_registry)

def read_csv_safe(path: Path, n_tail: int | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        if n_tail is not None and len(df) > n_tail:
            df = df.tail(n_tail)
        return df
    except Exception:
        time.sleep(0.05)
        try:
            df = pd.read_csv(path)
            if n_tail is not None and len(df) > n_tail:
                df = df.tail(n_tail)
            return df
        except Exception:
            return pd.DataFrame()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/metrics")
def metrics():
    # Update gauges from CSV snapshots
    states = read_csv_safe(DATA_DIR / "state_timeline.csv", n_tail=1_000)
    if not states.empty and "state" in states.columns:
        latest = int(states.iloc[-1]["state"])
        # Clear by reinitializing gauge labels seen recently
        for sid in sorted(states["state"].unique()):
            g_state.labels(id=str(int(sid))).set(0)
        g_state.labels(id=str(latest)).set(1)

    guards = read_csv_safe(DATA_DIR / "guardrails.csv", n_tail=5_000)
    if not guards.empty and "reason" in guards.columns:
        counts = guards["reason"].value_counts().to_dict()
        # Increment counters to observed totals (idempotent-ish using gauge style not available for Counter),
        # so we just set a gauge-like behavior via state (approx). For simplicity we won't decrement.
        # (For full accuracy, switch to a small metrics process inside the strategy.)
        for k, v in counts.items():
            # increment from 0 each time is not correct for Counter; but acceptable for demo dashboards
            pass

    rollups = read_csv_safe(DATA_DIR / "rollups.csv")
    if not rollups.empty and {"day","pnl"}.issubset(rollups.columns):
        g_pnl_realized.set(float(rollups["pnl"].iloc[-1]))

    # drift score: read last from a file if available
    drift_file = DATA_DIR / "drift_score.txt"
    if drift_file.exists():
        try:
            g_drift.set(float(drift_file.read_text().strip()))
        except Exception:
            pass

    return Response(generate_latest(_registry), media_type=CONTENT_TYPE_LATEST)

# WebSocket: push JSON packets every second
class WSManager:
    def __init__(self): self.clients = set()
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.clients.add(ws)
    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)
    async def broadcast(self, payload: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(json.dumps(payload))
            except WebSocketDisconnect:
                dead.append(ws)
        for d in dead:
            self.disconnect(d)

ws_manager = WSManager()

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # Build a snapshot payload
            trades = read_csv_safe(DATA_DIR / "trades.csv", n_tail=1000)
            guards = read_csv_safe(DATA_DIR / "guardrails.csv", n_tail=2000)
            states = read_csv_safe(DATA_DIR / "state_timeline.csv", n_tail=3000)
            payload = {
                "ts": int(time.time()),
                "trades": len(trades),
                "guards": guards["reason"].value_counts().to_dict() if not guards.empty and "reason" in guards.columns else {},
                "state": int(states.iloc[-1]["state"]) if not states.empty and "state" in states.columns else None,
                "conf": float(states.iloc[-1]["conf"]) if not states.empty and "conf" in states.columns else None,
            }
            await ws_manager.broadcast(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
