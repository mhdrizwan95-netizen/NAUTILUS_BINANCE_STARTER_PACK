from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json, time, httpx, os

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
    # lightweight health check to ML
    try:
        r = httpx.get(f"{ML_URL}/health", timeout=0.2).json()
        st["ml"] = r
    except Exception:
        st["ml"] = {"ok": False}
    return st

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
