from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi import WebSocket, WebSocketDisconnect
import json, time, httpx, os, glob, subprocess, shlex
import asyncio
from pathlib import Path as Path2

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

# ---------- New: mode metadata for dashboard ----------
@APP.get("/meta")
def meta():
    """Return metadata including trading mode."""
    from adapters.account_provider import BinanceAccountProvider
    mode = os.getenv("BINANCE_MODE", "live")
    exchanges = []
    provider = BinanceAccountProvider()
    if provider.spot_base != "":
        exchanges.append("SPOT")
    if provider.usdm_base != "":
        exchanges.append("USDM")
    if provider.coinm_base != "":
        exchanges.append("COIN-M")
    return {"ok": True, "mode": mode, "exchanges": exchanges}

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
    result = {
        "ok": True,
        "source": None,
        "snap_persist": None
    }

    try:
        # Try to reach one of the data sources we depend on
        # For simplicity, check if we can load metrics snapshot
        snap = _load_snap()
        if snap.metrics is not None:
            result["source"] = "snapshot"
    except Exception:
        pass

    # Check if snapshot persistence is working
    try:
        if SNAP_DIR.exists():
            # Recent file should exist if writer is active
            today_file = SNAP_DIR / (time.strftime("%Y-%m-%d") + ".jsonl")
            if today_file.exists() or (time.time() - SNAP_DIR.stat().st_ctime) < 300:  # created within 5 mins
                result["snap_persist"] = "ok"
            else:
                result["snap_persist"] = "stale"
        else:
            result["snap_persist"] = "no_dir"
    except Exception as e:
        result["snap_persist"] = f"error: {str(e)[:50]}"

    return result
# ---------------------------------------------------------------------------

SNAP_DIR = Path2("data/ops_snapshots")
SNAP_DIR.mkdir(parents=True, exist_ok=True)
RET_DAYS = int(os.getenv("SNAP_RETENTION_DAYS", "14"))
ALLOW_ACCOUNT_FALLBACK = os.getenv("ACCOUNT_DEMO_FALLBACK", "0").lower() in ("1", "true", "yes")

from adapters.account_provider import BinanceAccountProvider

# globals for account cache
ACCOUNT_CACHE: dict = {
    "balances": {"equity": 0.0, "cash": 0.0, "exposure": 0.0},
    "positions": [],
    "ts": 0,
    "source": "init",
}

def _load_demo_account() -> dict | None:
    """Return the most recent demo snapshot if Binance returns nothing."""
    try:
        files = sorted(SNAP_DIR.glob("*.jsonl"))
    except Exception:
        return None
    best: dict | None = None
    for path in reversed(files):
        try:
            lines = path.read_text().splitlines()
        except Exception:
            continue
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except Exception:
                continue
            acct = payload.get("account") or {}
            eq = float(acct.get("equity") or 0.0)
            cash = float(acct.get("cash") or 0.0)
            exposure = float(acct.get("exposure") or 0.0)
            positions = acct.get("positions") or []
            if eq or cash or exposure or positions:
                candidate = {
                    "equity": eq if eq else cash,
                    "cash": cash if cash else (eq if eq else 0.0),
                    "exposure": exposure,
                    "positions": positions,
                    "ts": payload.get("ts", time.time()),
                    "source": "fallback",
                }
                if positions:
                    return candidate
                if best is None:
                    best = candidate
    return best

def _derive_account_state(raw: dict, *, allow_fallback: bool = True) -> dict:
    """Normalize raw provider payload into the dashboard-friendly schema."""
    prev = ACCOUNT_CACHE
    prev_source = prev.get("source")
    can_use_prev = prev_source in {"binance", "cache"}
    used_prev = False
    fallback_used = False

    eq = float(raw.get("equity") or raw.get("account_equity_usd") or 0.0)
    cash = float(raw.get("cash") or raw.get("cash_usd") or 0.0)
    exposure = float(raw.get("exposure") or raw.get("gross_exposure_usd") or 0.0)
    positions = raw.get("positions") or []

    spot = float(raw.get("spot_equity_usdt") or 0.0)
    usdm = float(raw.get("usdm_equity_usdt") or 0.0)
    coinm = float(raw.get("coinm_equity_est") or 0.0)
    if eq == 0.0:
        eq = spot + usdm + coinm
    if cash == 0.0:
        cash = float(raw.get("balances", {}).get("cash", 0.0)) or eq
    if exposure == 0.0:
        exposure = float(raw.get("balances", {}).get("exposure", 0.0)) or exposure

    # Preserve previous readings if Binance temporarily returns zeros
    if eq == 0.0 and prev.get("equity") and can_use_prev:
        eq = float(prev.get("equity"))
        used_prev = True
    if cash == 0.0 and prev.get("cash"):
        if can_use_prev:
            cash = float(prev.get("cash"))
            used_prev = True
    if exposure == 0.0 and prev.get("exposure") and can_use_prev:
        exposure = float(prev.get("exposure"))
        used_prev = True
    if not positions and prev.get("positions") and can_use_prev:
        positions = prev.get("positions")
        used_prev = True

    if (
        allow_fallback
        and ALLOW_ACCOUNT_FALLBACK
        and eq == 0.0
        and cash == 0.0
        and exposure == 0.0
        and not positions
    ):
        demo = _load_demo_account()
        if demo:
            eq = demo.get("equity", eq)
            cash = demo.get("cash", cash if cash else eq)
            exposure = demo.get("exposure", exposure)
            positions = demo.get("positions", positions)
            fallback_used = True

    ts = raw.get("ts") if isinstance(raw.get("ts"), (int, float)) else time.time()
    source = "binance" if raw else "none"
    if fallback_used:
        source = "fallback"
    elif used_prev:
        source = "cache"

    return {
        "equity": float(eq),
        "cash": float(cash),
        "exposure": float(exposure),
        "positions": positions,
        "ts": ts,
        "source": source,
    }

def _update_metrics_account_fields(equity: float, cash: float, exposure: float) -> None:
    try:
        snap = _load_snap()
        metrics = snap.metrics.__dict__.copy()
        updated = False
        for key, val in {
            "account_equity_usd": float(equity),
            "cash_usd": float(cash),
            "gross_exposure_usd": float(exposure),
        }.items():
            if abs(metrics.get(key, 0.0) - val) > 1e-6:
                metrics[key] = val
                updated = True
        if updated:
            _save_snap(_Snapshot(metrics=_Metrics(**metrics), ts=time.time()))
    except Exception as exc:
        print("account metrics update failed:", exc, flush=True)

def _publish_account_snapshot(state: dict) -> None:
    ACCOUNT_CACHE["equity"] = state.get("equity", 0.0)
    ACCOUNT_CACHE["cash"] = state.get("cash", 0.0)
    ACCOUNT_CACHE["exposure"] = state.get("exposure", 0.0)
    ACCOUNT_CACHE["balances"] = {
        "equity": ACCOUNT_CACHE["equity"],
        "cash": ACCOUNT_CACHE["cash"],
        "exposure": ACCOUNT_CACHE["exposure"],
    }
    ACCOUNT_CACHE["positions"] = state.get("positions", [])
    ACCOUNT_CACHE["ts"] = state.get("ts", time.time())
    ACCOUNT_CACHE["source"] = state.get("source", "binance")
    if ACCOUNT_CACHE["source"] != "fallback":
        _update_metrics_account_fields(ACCOUNT_CACHE["equity"], ACCOUNT_CACHE["cash"], ACCOUNT_CACHE["exposure"])

INC = []
INC_MAX = 200

# account polling for real API integration
def _poll_account():
    try:
        prov = BinanceAccountProvider()
        while True:
            try:
                snap = prov.snapshot()
                state = _derive_account_state(snap)
                _publish_account_snapshot(state)
            except Exception as e:
                # keep running; log minimal in container
                print("account poll error:", repr(e))
            POLL_SEC = float(os.getenv("DEMO_POLL_SEC","5"))
            time.sleep(POLL_SEC)
    except Exception:
        # Graceful degradation - don't crash if DEMO_API_BASE not set
        if ALLOW_ACCOUNT_FALLBACK:
            fallback = _load_demo_account()
            if fallback:
                _publish_account_snapshot(fallback)

@APP.on_event("startup")
def _start_poll():
    import threading
    threading.Thread(target=_poll_account, daemon=True).start()

# expose account endpoints
@APP.get("/account_snapshot")
def account_snapshot():
    return ACCOUNT_CACHE

@APP.get("/positions")
def positions():
    return {"positions": ACCOUNT_CACHE.get("positions", [])}

ACC = BinanceAccountProvider()  # fallback for compatibility

@APP.post("/incidents")
def create_incident(item: dict):
    item.setdefault("ts", time.time())
    INC.append(item)
    del INC[:-INC_MAX]  # keep only last INC_MAX
    # broadcast to WebSocket clients
    for ws in list(WSS):
        try:
            ws.send_json(item)
        except Exception:
            pass
    return {"ok": True}

@APP.get("/incidents")
def list_incidents():
    return {"items": INC[-50:]}

WSS = set()

@APP.websocket("/ws/incidents")
async def ws_incidents(websocket: WebSocket):
    await websocket.accept()
    WSS.add(websocket)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        WSS.discard(websocket)

async def _snap_loop():
    while True:
        try:
            raw_account = await ACC.fetch()
            state = _derive_account_state(raw_account)
            _publish_account_snapshot(state)
            snap = _load_snap()
            payload = {
                "ts": time.time(),
                "metrics": snap.metrics.__dict__.copy(),
                "account": state,
            }
            fn = SNAP_DIR / (time.strftime("%Y-%m-%d") + ".jsonl")
            with fn.open("a") as f:
                f.write(json.dumps(payload) + "\n")
            # retention
            cutoff = time.time() - RET_DAYS * 86400
            for p in SNAP_DIR.glob("*.jsonl"):
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
        except Exception as e:
            print("snap_loop err:", e, flush=True)
            fallback = _derive_account_state({}, allow_fallback=True)
            _publish_account_snapshot(fallback)
        await asyncio.sleep(60)

@APP.on_event("startup")
async def _bg():
    asyncio.create_task(_snap_loop())
