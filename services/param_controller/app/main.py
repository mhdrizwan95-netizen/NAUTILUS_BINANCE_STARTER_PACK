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
    return {"status": "ok"}


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
    history = store.fetch_outcomes(settings.PC_DB, strategy, instrument)
    history_feature_keys = {k for _, _, feats in history for k in feats.keys()}
    feat_keys = sorted(set(features.keys()) | history_feature_keys)
    if not feat_keys:
        feat_keys = ["bias"]
        features = {"bias": 1.0}
    x = np.array([features.get(k, 0.0) for k in feat_keys], dtype=float)
    K = len(presets)
    X = np.vstack([x for _ in range(K)])
    bandit = LinTS(d=x.size, l2=settings.L2)
    preset_index = {pid: idx for idx, (pid, _) in enumerate(presets)}
    for preset_id, reward, feat_dict in history:
        idx = preset_index.get(preset_id)
        if idx is None:
            continue
        vec = np.array([feat_dict.get(k, 0.0) for k in feat_keys], dtype=float)
        bandit.update(idx, vec, reward)
    # Sample from posterior conditioned on historical outcomes
    k = bandit.choose(X)
    pid, params = presets[k]
    config_id = f"{strategy}:{instrument}:{pid}"
    return {
        "config_id": config_id,
        "params": params,
        "policy_version": "0.1.0",
        "features_used": feat_keys,
    }


@app.post("/learn/outcome/{strategy}/{instrument}/{preset_id}")
def report_outcome(
    strategy: str, instrument: str, preset_id: str, body: Dict[str, Any]
):
    reward = float(body.get("reward", 0.0))
    features = body.get("features", {})
    store.log_outcome(settings.PC_DB, strategy, instrument, preset_id, reward, features)
    return {"ok": True}
