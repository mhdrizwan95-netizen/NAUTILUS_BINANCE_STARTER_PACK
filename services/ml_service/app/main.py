from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from loguru import logger
from contextlib import asynccontextmanager
from .config import settings
from .auth import require_role
from .schemas import TrainRequest, TrainResponse, ModelInfo
from .trainer import train_once
from .inference import start_watchdog, predict_proba
from . import model_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start model file watcher
    start_watchdog()
    yield


app = FastAPI(title="ML Service (HMM)", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/model", response_model=ModelInfo)
def model_info():
    cur = model_store.get_current_paths()
    active = None
    metrics = None
    if cur:
        _, _, meta = cur
        active = meta.parent.name if hasattr(meta, 'parent') else None
        # reload via helper to get dict
        _, _, m = model_store.load_current()
        metrics = m
    return ModelInfo(active_version=active, registry_size=model_store.registry_size(), metrics=metrics)


@app.post("/train", response_model=TrainResponse, dependencies=[Depends(require_role("trainer", "admin"))])
def train(req: TrainRequest):
    res = train_once(n_states=req.n_states, tag=req.tag, promote=req.promote)
    meta = res["metadata"]
    version_id = res["version_dir"].split("/")[-1]
    return TrainResponse(
        version_id=version_id,
        metric_name=meta.get("metric_name", "val_log_likelihood"),
        metric_value=float(meta.get("metric_value", 0.0)),
        promoted=bool(res.get("promoted", False)),
        message="ok"
    )


@app.post("/predict")
def predict(payload: dict):
    # expects {"logret": [..]}
    post = predict_proba(payload.get("logret", []))
    return JSONResponse(post)
