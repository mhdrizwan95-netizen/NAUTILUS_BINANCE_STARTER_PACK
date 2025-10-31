
from fastapi import FastAPI, HTTPException
from typing import Dict, Any
import numpy as np
from loguru import logger
from .config import settings
from . import store
from .bandit import LinTS

app = FastAPI(title="param-controller", version="0.1.0")

@app.on_event("startup")
def on_start():
    store.init(settings.PC_DB)
    logger.info("param-controller up")

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/preset/register/{strategy}/{instrument}")
def register_preset(strategy: str, instrument: str, body: Dict[str, Any]):
    pid = body.get("preset_id")
    params = body.get("params")
    if not pid or not isinstance(params, dict):
        raise HTTPException(400, "preset_id and params required")
    store.upsert_preset(settings.PC_DB, strategy, instrument, pid, params)
    return {"ok": True}

@app.get("/param/{strategy}/{instrument}")
def get_param(strategy: str, instrument: str, features: Dict[str, float] = {}):
    presets = store.list_presets(settings.PC_DB, strategy, instrument)
    if not presets:
        raise HTTPException(404, "no presets registered")
    # Build K x d design with same x for each arm
    feat_keys = sorted(features.keys())
    x = np.array([features[k] for k in feat_keys], dtype=float)
    if x.size == 0:
        # fallback: bias only
        x = np.array([1.0], dtype=float)
    K = len(presets)
    X = np.vstack([x for _ in range(K)])
    bandit = LinTS(d=x.size, l2=settings.L2)
    # We don't persist the bandit posterior in this minimal example; for production,
    # persist A/b per (strategy,instrument) and warm-start here.
    k = bandit.choose(X)
    pid, params = presets[k]
    config_id = f"{strategy}:{instrument}:{pid}"
    return {"config_id": config_id, "params": params, "policy_version": "0.1.0", "features_used": feat_keys}

@app.post("/learn/outcome/{strategy}/{instrument}/{preset_id}")
def report_outcome(strategy: str, instrument: str, preset_id: str, body: Dict[str, Any]):
    reward = float(body.get("reward", 0.0))
    features = body.get("features", {})
    store.log_outcome(settings.PC_DB, strategy, instrument, preset_id, reward, features)
    return {"ok": True}
