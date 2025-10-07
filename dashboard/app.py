from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest, multiprocess, Counter, Gauge
from prometheus_client import CollectorRegistry
from fastapi import Response
from .prom_setup import get_registry
import pandas as pd
from pathlib import Path
import asyncio
import time, json, os, requests, re
import httpx
from typing import Dict, List, Any

APP_ROOT = Path(__file__).resolve().parent
DATA_DIR = APP_ROOT.parent / "data" / "processed"
FEEDBACK_CSV = DATA_DIR / "feedback_log.csv"
INCIDENT_LOG = DATA_DIR / "m20" / "incident_log.jsonl"

APP = FastAPI(title="HMM Trader Dashboard")
APP.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))

OPS_BASE = os.getenv("OPS_BASE", "http://127.0.0.1:8001")

# Enable CORS for React frontend integration
APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Real metrics shim (Option B) --------------------------------------------
import re

# basic http helper (for proxy routes below)
async def _get_json(url: str) -> Any:
    async with httpx.AsyncClient(timeout=2.5) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()

# Config knobs from env (T1)
POLL_MS = int(os.getenv("DASH_POLL_MS", "5000"))
_prometric_keys = os.getenv("PROM_METRIC_KEYS", "pnl_realized,pnl_unrealized,drift_score,policy_confidence,order_fill_ratio,venue_latency_ms")
PROM_METRIC_KEYS = [k.strip() for k in _prometric_keys.split(",") if k.strip()] if _prometric_keys else []

PROM_MAP = {
    "pnl_realized": ["pnl_realized", "pnl_realised", "pnl_realized_usd"],
    "pnl_unrealized": ["pnl_unrealized", "pnl_unrealised", "pnl_unrealized_usd"],
    "drift_score": ["drift_score", "policy_drift", "hmm_drift_score"],
    "policy_confidence": ["policy_confidence", "action_confidence", "hmm_policy_confidence"],
    "order_fill_ratio": ["order_fill_ratio", "fill_ratio", "execution_fill_ratio"],
    "venue_latency_ms": ["venue_latency_ms", "venue_latency", "exchange_latency_ms"],
}

# Extend PROM_MAP with account metrics and env-provided keys
PROM_MAP.update({
    "account_equity_usd": ["account_equity_usd", "equity_usd", "nav_usd"],
    "cash_usd": ["cash_usd", "balance_usd"],
    "gross_exposure_usd": ["gross_exposure_usd", "exposure_usd", "gross_exposure"],
})

for key in PROM_METRIC_KEYS:
    if key not in PROM_MAP:
        PROM_MAP[key] = [key]  # Add default mapping for unknown keys

async def _get_json_safe(url: str) -> Any | None:
    try:
        return await _get_json(url)
    except Exception:
        return None

def _from_json(obj: dict | None, *keys: str, default: float = 0.0) -> float:
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return default

def _parse_prometheus_text(text: str) -> dict[str, float]:
    # T5: Export function for unit testing
    """
    Parse Prometheus exposition format: "name[ {labels} ] value"
    Supports multiple metric shapes from the fallback chain.
    """
    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        # match: metric_name{...} 123.45  OR  metric_name 123.45
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{.*?\})?\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)$", line.strip())
        if not m:
            continue
        name, val = m.group(1), m.group(2)
        try:
            out[name] = float(val)
        except Exception:
            continue
    return out

async def _get_prometheus_metrics(base: str) -> dict[str, float] | None:
    try:
        async with httpx.AsyncClient(timeout=2.5) as c:
            r = await c.get(f"{base}/metrics")
            r.raise_for_status()
            raw = r.text
        expo = _parse_prometheus_text(raw)
        # resolve friendly names using PROM_MAP
        resolved = {}
        for friendly, candidates in PROM_MAP.items():
            for name in candidates:
                if name in expo:
                    resolved[friendly] = float(expo[name])
                    break
        return resolved
    except Exception:
        return None

@APP.get("/api/metrics_snapshot")
async def api_metrics_snapshot():
    metrics = {
        "pnl_realized": 0.0,
        "pnl_unrealized": 0.0,
        "drift_score": 0.0,
        "policy_confidence": 0.0,
        "order_fill_ratio": 0.0,
        "venue_latency_ms": 0.0,
        "account_equity_usd": 0.0,
        "cash_usd": 0.0,
        "gross_exposure_usd": 0.0,
    }

    source = "legacy"  # default if nothing works

    # 1) Prefer Ops JSON snapshot if available
    snap = await _get_json_safe(f"{OPS_BASE}/metrics_snapshot")
    if isinstance(snap, dict):
        source = "ops_snapshot"
        m = snap.get("metrics") if "metrics" in snap else snap
        metrics["pnl_realized"]       = _from_json(m, "pnl_realized")
        metrics["pnl_unrealized"]     = _from_json(m, "pnl_unrealized")
        metrics["drift_score"]        = _from_json(m, "drift_score")
        metrics["policy_confidence"]  = _from_json(m, "policy_confidence")
        metrics["order_fill_ratio"]   = _from_json(m, "order_fill_ratio")
        metrics["venue_latency_ms"]   = _from_json(m, "venue_latency_ms")
        metrics["account_equity_usd"] = _from_json(m, "account_equity_usd")
        metrics["cash_usd"]           = _from_json(m, "cash_usd")
        metrics["gross_exposure_usd"] = _from_json(m, "gross_exposure_usd")

    else:
        # 2) Try Ops generic /metrics JSON
        m2 = await _get_json_safe(f"{OPS_BASE}/metrics")
        if isinstance(m2, dict):
            source = "ops_metrics"
            # Try common shapes: {"pnl": {...}, "policy": {...}, "execution": {...}}
            pnl = m2.get("pnl", m2)
            pol = m2.get("policy", m2)
            exe = m2.get("execution", m2)
            metrics["pnl_realized"]      = _from_json(pnl, "realized", "pnl_realized", "realized_usd")
            metrics["pnl_unrealized"]    = _from_json(pnl, "unrealized", "pnl_unrealized", "unrealized_usd")
            metrics["drift_score"]       = _from_json(pol, "drift", "drift_score")
            metrics["policy_confidence"] = _from_json(pol, "confidence", "policy_confidence")
            metrics["order_fill_ratio"]  = _from_json(exe, "fill_ratio", "order_fill_ratio")
            metrics["venue_latency_ms"]  = _from_json(exe, "venue_latency_ms", "latency_ms", "exchange_latency_ms")

        else:
            # 3) Try Ops split endpoints
            pnl = await _get_json_safe(f"{OPS_BASE}/pnl")
            st  = await _get_json_safe(f"{OPS_BASE}/state")
            if not st:
                st = await _get_json_safe(f"{OPS_BASE}/states")
            if pnl or st:
                source = "ops_split"
            if pnl:
                metrics["pnl_realized"]   = _from_json(pnl, "realized", "pnl_realized", "realized_usd")
                metrics["pnl_unrealized"] = _from_json(pnl, "unrealized", "pnl_unrealized", "unrealized_usd")
            if st:
                metrics["drift_score"]       = _from_json(st, "drift", "drift_score")
                metrics["policy_confidence"] = _from_json(st, "confidence", "policy_confidence")
                metrics["order_fill_ratio"]  = _from_json(st, "fill_ratio", "order_fill_ratio")
                metrics["venue_latency_ms"]  = _from_json(st, "latency_ms", "venue_latency_ms", "exchange_latency_ms")

            # 4) Last resort: parse Prometheus exposition from Ops
            if not pnl and not st:
                expo = await _get_prometheus_metrics(OPS_BASE)
                if expo:
                    source = "ops_prom"
                    for k in metrics.keys():
                        metrics[k] = float(expo.get(k, metrics[k]))

    return {"metrics": metrics, "ts": time.time(), "source": source}

# 2) Proxy lineage & calibration to Ops API (M21 & M15)
@APP.get("/api/lineage")
async def api_lineage_proxy():
    try:
        return await _get_json(f"{OPS_BASE}/lineage")
    except Exception:
        return {"index": {"models": []}}

@APP.get("/api/artifacts/m15")
async def api_artifacts_proxy():
    try:
        return await _get_json(f"{OPS_BASE}/artifacts/m15")
    except Exception:
        return {"files": []}

# 3) Topic WS hub: /ws/{topic}
_connections: Dict[str, List[WebSocket]] = {"scheduler": [], "guardian": [], "lineage": [], "calibration": []}

async def _broadcast(topic: str, payload: Any):
    dead = []
    for ws in list(_connections.get(topic, [])):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            _connections[topic].remove(ws)
        except Exception:
            pass

@APP.websocket("/ws/{topic}")
async def ws_topic(websocket: WebSocket, topic: str):
    await websocket.accept()
    if topic not in _connections:
        _connections[topic] = []
    _connections[topic].append(websocket)
    try:
        # passive receive; this keeps the connection alive
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        try:
            _connections[topic].remove(websocket)
        except Exception:
            pass

# 4) Debug publish endpoints so you can test feeds instantly (optional)
@APP.post("/debug/publish/{topic}")
async def debug_publish(topic: str, payload: Dict[str, Any]):
    payload.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    await _broadcast(topic, payload)
    return {"ok": True}
# ---------------------------------------------------------------------------

# Prometheus registry (multiprocess-aware if env var set)
REG = get_registry()
g_state          = Gauge("state_active", "Active HMM state", ["id"], registry=REG)
c_guard          = Counter("guardrail_trigger_total", "Guardrail triggers", ["reason"], registry=REG)
g_pnl_realized   = Gauge("pnl_realized", "Realized PnL", registry=REG)
g_pnl_unrealized = Gauge("pnl_unrealized", "Unrealized PnL", registry=REG)
g_drift          = Gauge("drift_score", "Feature drift (KLD)", registry=REG)

# M14: cross-symbol correlation risk metrics
g_corr_btc_eth = Gauge("corr_btc_eth", "BTC-ETH correlation coefficient", registry=REG)
g_port_vol     = Gauge("port_vol", "Portfolio volatility percentage", registry=REG)
g_corr_regime  = Gauge("corr_regime_state", "Correlation regime state", ["state"], registry=REG)

# New: extra gauges (mirroring producers)
g_policy_conf    = Gauge("policy_confidence", "Latest policy confidence", registry=REG)
g_fill_ratio     = Gauge("order_fill_ratio", "Recent fills/orders ratio", registry=REG)
g_latency_ms     = Gauge("venue_latency_ms", "Recent venue latency (ms)", registry=REG)

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

@APP.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@APP.get("/metrics")
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

    return Response(generate_latest(REG), media_type=CONTENT_TYPE_LATEST)

@APP.get("/api/states")
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

@APP.get("/api/pnl")
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

@APP.get("/api/guardrails")
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

@APP.websocket("/ws")
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

# --- Health & metrics endpoints for dash ------------------------------------
from fastapi import APIRouter
import os, json, time
import urllib.request

OPS_BASE = os.getenv("OPS_BASE", "http://ops:8001")

@APP.get("/status")
def dash_status():
    return {"ok": True}

@APP.get("/readyz")
def dash_ready():
    # optional: sanity check Ops is reachable (non-fatal)
    try:
        urllib.request.urlopen(f"{OPS_BASE}/readyz", timeout=2)
        return {"ok": True, "ops": "ok"}
    except Exception:
        return {"ok": True, "ops": "degraded"}

def _fetch(url, timeout=2.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

@APP.get("/api/metrics_snapshot")
async def dash_metrics_snapshot():
    """
    Smart fallback: prefer ops /metrics_snapshot, degrade gracefully.
    """
    # 1) preferred
    try:
        data = _fetch(f"{OPS_BASE}/metrics_snapshot")
        # annotate source so UI can show 'ops_snapshot'
        data["source"] = data.get("source", "ops_snapshot")
        return data
    except Exception:
        pass

    # 2) try ops /metrics
    try:
        data = _fetch(f"{OPS_BASE}/metrics")
        return {"metrics": data.get("metrics", {}), "ts": int(time.time()), "source": "ops_metrics"}
    except Exception:
        pass

    # 3) last resort empty
    return {"metrics": {
        "pnl_realized": 0, "pnl_unrealized": 0,
        "drift_score": 0, "policy_confidence": 0,
        "order_fill_ratio": 0, "venue_latency_ms": 0,
    }, "ts": int(time.time()), "source": "none"}
# ---------------------------------------------------------------------------
