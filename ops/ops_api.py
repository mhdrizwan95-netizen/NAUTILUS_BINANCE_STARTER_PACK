from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
import json, time, httpx, os, glob, subprocess, shlex

# --- metrics snapshot surface -----------------------------------------------
from ops.telemetry_store import load as _load_snap, save as _save_snap, Metrics as _Metrics, Snapshot as _Snapshot
import time

class MetricsIn(BaseModel):
    pnl_realized: float | None = None
    pnl_unrealized: float | None = None
    drift_score: float | None = None
    policy_confidence: float | None = None
    order_fill_ratio: float | None = None
    venue_latency_ms: float | None = None
    # NEW: account metrics
    account_equity_usd: float | None = None
    cash_usd: float | None = None
    gross_exposure_usd: float | None = None

APP = FastAPI(title="Ops API")

@APP.get("/status")
def status():
    return {"ok": True}

@APP.get("/readyz")
def readyz():
    return {"ok": True}


# T6: Auth token for control actions
EXPECTED_TOKEN = os.getenv("OPS_API_TOKEN", "dev-token")  # Change in production

def _check_auth(request):
    """Check X-OPS-TOKEN header for control actions."""
    auth_header = request.headers.get("X-OPS-TOKEN")
    if not auth_header or auth_header != EXPECTED_TOKEN:
        raise HTTPException(401, "Invalid or missing X-OPS-TOKEN")

@APP.get("/metrics_snapshot")
def get_metrics_snapshot():
    s = _load_snap()
    return {"metrics": s.metrics.__dict__, "ts": s.ts}

@APP.post("/metrics_snapshot")
def post_metrics_snapshot(m: MetricsIn):
    s = _load_snap()
    d = s.metrics.__dict__.copy()
    # apply partial updates
    for k, v in m.dict(exclude_unset=True).items():
        if v is not None:
            d[k] = float(v)
    new = _Snapshot(metrics=_Metrics(**d), ts=time.time())
    _save_snap(new)
    return {"ok": True, "ts": new.ts}
# ---------------------------------------------------------------------------

# Enable CORS for React frontend integration
APP.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Next.js dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_FILE = Path(__file__).resolve().parent / "state.json"
ML_URL = os.getenv("HMM_URL", "http://127.0.0.1:8010")

class KillReq(BaseModel):
    enabled: bool

class RetrainReq(BaseModel):
    feature_sequences: list
    labels: list[int] | None = None

@APP.get("/status")
def status():
    st = {"ts": int(time.time()), "trading_enabled": True}
    if STATE_FILE.exists():
        try:
            st.update(json.loads(STATE_FILE.read_text()))
        except Exception:
            pass

    # Extend with richer runtime info for the dash
    try:
        # Macro/micro state snapshots if available
        macro_state = int(os.environ.get("MACRO_STATE", "1"))
        st["macro_state"] = macro_state
        # Pull lineage head (if exists)
        lineage_path = os.path.join("data", "memory_vault", "lineage_index.json")
        if os.path.exists(lineage_path):
            with open(lineage_path, "r") as f:
                j = json.load(f)
            st["lineage_total_generations"] = len(j.get("models", []))
            st["lineage_latest"] = j["models"][-1] if j.get("models") else {}
    except Exception as e:
        st["status_warning"] = f"{e}"

    # lightweight health check to ML
    try:
        r = httpx.get(f"{ML_URL}/health", timeout=0.2).json()
        st["ml"] = r
    except Exception:
        st["ml"] = {"ok": False}
    return {"ok": True, "state": st}

@APP.post("/kill")
def kill(req: KillReq, request: Request):
    _check_auth(request)
    state = {"trading_enabled": bool(req.enabled)}
    STATE_FILE.write_text(json.dumps(state))
    return {"ok": True, "state": state}

@APP.post("/retrain")
def retrain(req: RetrainReq, request: Request):
    _check_auth(request)
    # proxy to ML service
    try:
        r = httpx.post(f"{ML_URL}/train", json={"symbol":"BTCUSDT","feature_sequences": req.feature_sequences, "labels": req.labels or []}, timeout=30.0)
        return {"ok": True, "ml_response": r.json()}
    except Exception as e:
        raise HTTPException(500, f"ML retrain failed: {e}")

# ---------- New: artifacts + lineage ----------
@APP.get("/artifacts/m15")
def list_artifacts_m15():
    """Return calibration PNGs for gallery (reward_heatmap, policy_boundary, rolling_winrate)."""
    base = os.path.join("data", "processed", "calibration")
    files = sorted(glob.glob(os.path.join(base, "*.png")))
    return {"ok": True, "files": files}

@APP.get("/lineage")
def get_lineage():
    """Return Memory Vault lineage index + suggested graph path."""
    idx = os.path.join("data", "memory_vault", "lineage_index.json")
    graph = os.path.join("data", "memory_vault", "lineage_graph.png")
    if not os.path.exists(idx):
        return {"ok": False, "error": "no lineage index"}
    with open(idx, "r") as f:
        j = json.load(f)
    return {"ok": True, "index": j, "graph": graph if os.path.exists(graph) else None}

# ---------- New: canary promote ----------
class PromoteReq(BaseModel):
    target_tag: str

@APP.post("/canary_promote")
def canary_promote(req: PromoteReq, request: Request) -> dict:
    _check_auth(request)
    """Promote a canary model tag into active use."""
    try:
        cmd = "./ops/m11_canary_promote.sh " + shlex.quote(req.target_tag)
        subprocess.check_call(cmd, shell=True)
        return {"ok": True, "promoted": req.target_tag}
    except Exception as e:
        raise HTTPException(500, f"promotion failed: {e}")

# ---------- Optional: flush guardrails ----------
@APP.post("/flush_guardrails")
def flush_guardrails():
    """Soft-reset guardrail counters (used for incident recovery testing)."""
    try:
        # No-op placeholder; implement if you persist counters externally
        return {"ok": True, "flushed": True}
    except Exception as e:
        raise HTTPException(500, f"flush failed: {e}")

# ---------- T3: Health & readiness endpoints ----------
@APP.get("/healthz")
def healthz():
    """Fast health check - always returns ok."""
    return {"ok": True}

@APP.get("/readyz")
def readyz():
    """Readiness check - verifies can reach at least one Ops data source."""
    try:
        # Try to reach one of the data sources we depend on
        # For simplicity, check if we can load metrics snapshot
        snap = _load_snap()
        if snap.metrics is not None:
            return {"ok": True, "source": "snapshot"}
    except Exception:
        pass

    # Try other sources like the status endpoint itself
    try:
        # If we can get any status info, we're ready
        status()
        return {"ok": True, "source": "status"}
    except Exception:
        pass

    # If all sources fail, return degraded state
    return {"ok": False, "error": "no data sources available"}
# ---------------------------------------------------------------------------

# ---------- ACC-5: Optional account snapshot endpoint ----------
@APP.get("/account_snapshot")
def account_snapshot():
    """Return positions table and account summary."""
    snap = _load_snap()
    # Return latest cached values
    return {
        "equity_usd": snap.metrics.account_equity_usd,
        "cash_usd": snap.metrics.cash_usd,
        "positions": []  # TODO: implement real positions fetching if needed
    }

# --- health endpoints ---
@APP.get("/status")
def status():
    return {"ok": True}

@APP.get("/readyz")
def readyz():
    # keep it light; adjust if you want deeper checks
    return {"ok": True}
