from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest, multiprocess, Counter, Gauge
from prometheus_client import CollectorRegistry
from fastapi import Response
import pandas as pd
from pathlib import Path
import asyncio
import time, json, os, requests

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = APP_ROOT.parent / "data" / "processed"
FEEDBACK_CSV = DATA_DIR / "feedback_log.csv"
INCIDENT_LOG = DATA_DIR / "m20" / "incident_log.jsonl"

app = FastAPI(title="HMM Trader Dashboard")
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))

# Enable CORS for React frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Next.js dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# FastAPI + WS topics --------------
WS_CLIENTS = {"guardian": set(), "scheduler": set(), "lineage": set(), "calibration": set()}

@app.websocket("/ws/{topic}")
async def ws_topic(websocket: WebSocket, topic: str):
    await websocket.accept()
    if topic not in WS_CLIENTS: WS_CLIENTS[topic] = set()
    WS_CLIENTS[topic].add(websocket)
    try:
        while True:
            # passive (server-push only)
            await asyncio.sleep(60)
    except Exception:
        pass
    finally:
        WS_CLIENTS[topic].discard(websocket)

async def _broadcast(topic: str, payload: dict):
    dead = []
    for ws in list(WS_CLIENTS.get(topic, [])):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        WS_CLIENTS[topic].discard(ws)

# Lightweight REST for UI --------------
OPS_BASE = os.environ.get("OPS_BASE", "http://127.0.0.1:8001")  # point to ops_api service

@app.get("/api/metrics_snapshot")
def metrics_snapshot():
    """Compact strip for: pnl, drift, policy_conf, fill_ratio, latency, corr_regime."""
    # Pull directly from local registry (these gauges are set by your loop)
    snap = {
        "pnl_realized": g_pnl_realized._value.get(),
        "pnl_unrealized": g_pnl_unrealized._value.get(),
        "drift_score": g_drift._value.get(),
        "policy_confidence": g_policy_conf._value.get(),
        "order_fill_ratio": g_fill_ratio._value.get(),
        "venue_latency_ms": g_latency_ms._value.get(),
    }
    # Regime label if any
    snap["corr_regime"] = "unknown"
    return {"ok": True, "metrics": snap}

@app.get("/api/artifacts/m15")
def proxy_artifacts():
    r = requests.get(f"{OPS_BASE}/artifacts/m15", timeout=3)
    return r.json()

@app.get("/api/lineage")
def proxy_lineage():
    r = requests.get(f"{OPS_BASE}/lineage", timeout=3)
    return r.json()

# Prometheus registry (single-process simple mode)
_registry = CollectorRegistry()
g_state          = Gauge("state_active", "Active HMM state", ["id"], registry=_registry)
c_guard          = Counter("guardrail_trigger_total", "Guardrail triggers", ["reason"], registry=_registry)
g_pnl_realized   = Gauge("pnl_realized", "Realized PnL", registry=_registry)
g_pnl_unrealized = Gauge("pnl_unrealized", "Unrealized PnL", registry=_registry)
g_drift          = Gauge("drift_score", "Feature drift (KLD)", registry=_registry)

# M14: cross-symbol correlation risk metrics
g_corr_btc_eth = Gauge("corr_btc_eth", "BTC-ETH correlation coefficient", registry=_registry)
g_port_vol     = Gauge("port_vol", "Portfolio volatility percentage", registry=_registry)
g_corr_regime  = Gauge("corr_regime_state", "Correlation regime state", ["state"], registry=_registry)

# New: extra gauges (mirroring producers)
g_policy_conf    = Gauge("policy_confidence", "Latest policy confidence", registry=_registry)
g_fill_ratio     = Gauge("order_fill_ratio", "Recent fills/orders ratio", registry=_registry)
g_latency_ms     = Gauge("venue_latency_ms", "Recent venue latency (ms)", registry=_registry)

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

@app.get("/api/states")
def get_states():
    s = read_csv_safe(DATA_DIR / "state_timeline.csv", n_tail=10000)
    hist = {}
    macro_hist = {}
    latest = None
    if not s.empty:
        # Count micro states
        if "state" in s.columns:
            hist = s["state"].value_counts().sort_index().to_dict()
        # Count macro states if available
        if "macro_state" in s.columns:
            macro_hist = s["macro_state"].value_counts().sort_index().to_dict()
        # Latest state info
        if len(s) > 0:
            last_row = s.iloc[-1]
            latest = {
                "state": int(last_row.get("state", 0)),
                "macro_state": int(last_row.get("macro_state", 1)),
                "conf": float(last_row.get("conf", 0.0)),
                "ts_ns": int(last_row.get("ts_ns", 0))
            }
    return {"hist": hist, "macro_hist": macro_hist, "latest": latest}

@app.get("/api/pnl")
def api_pnl():
    if not FEEDBACK_CSV.exists():
        return {"ts": [], "pnl": [], "equity": []}
    df = pd.read_csv(FEEDBACK_CSV)
    ts = pd.to_datetime(df["ts"], errors="coerce") if "ts" in df.columns else pd.Series(range(len(df)))
    pnl = df.get("pnl", pd.Series([0]*len(df))).astype(float).fillna(0.0)
    equity = pnl.cumsum()
    return {
        "ts": ts.astype(str).tolist(),
        "pnl": pnl.round(6).tolist(),
        "equity": equity.round(6).tolist(),
    }

@app.get("/api/guardrails")
def api_guardrails():
    if not INCIDENT_LOG.exists():
        return {"count_5m": 0, "recent": []}
    try:
        lines = INCIDENT_LOG.read_text().strip().splitlines()[-100:]
        records = []
        for ln in lines:
            try:
                records.append(json.loads(ln))
            except Exception:
                pass
        return {"count_5m": len(records), "recent": records[-10:]}
    except Exception:
        return {"count_5m": 0, "recent": []}

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
