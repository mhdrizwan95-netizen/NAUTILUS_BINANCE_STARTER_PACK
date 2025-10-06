# M3: FastAPI ML service (HMM + Policy)
from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np

app = FastAPI()

# In M3, load real models; for M0..M2, return HOLD actions.
class InferReq(BaseModel):
    symbol: str
    features: list[float]
    ts: int

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/infer")
def infer(req: InferReq):
    x = np.array(req.features, dtype=np.float32)
    # Placeholder state & confidence
    state = int(np.argmax([0.4, 0.6, 0.0]))
    probs = [0.4, 0.6, 0.0]
    confidence = float(max(probs))
    action = {"side": "HOLD", "qty": 0, "limit_px": None}
    return {"state": state, "probs": probs, "confidence": confidence, "action": action}

# TODO M3: add /partial_fit and /train endpoints and persist models in ml_service/model_store
