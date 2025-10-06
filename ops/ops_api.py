from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json, time, httpx, os, glob, subprocess, shlex

APP = FastAPI(title="Ops API")

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
def kill(req: KillReq):
    state = {"trading_enabled": bool(req.enabled)}
    STATE_FILE.write_text(json.dumps(state))
    return {"ok": True, "state": state}

@APP.post("/retrain")
def retrain(req: RetrainReq):
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
def canary_promote(req: PromoteReq) -> dict:
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
