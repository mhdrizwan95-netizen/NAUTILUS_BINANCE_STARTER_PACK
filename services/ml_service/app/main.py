from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from shared.dry_run import install_dry_run_guard, log_dry_run_banner

from . import model_store
from .auth import require_role
from .inference import predict_proba, start_watchdog
from .schemas import (
    ModelInfo,
    PredictRequest,
    PredictResponse,
    TrainRequest,
    TrainResponse,
    ModelListResponse,
    ModelVersion,
    PageMetadata,
)
from .trainer import train_once


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    start_watchdog()
    yield


app = FastAPI(title="ml-service (HMM)", version="0.2.0", lifespan=lifespan)
install_dry_run_guard(app, allow_paths={"/health", "/model", "/train"})
log_dry_run_banner("services.ml_service")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/model", response_model=ModelInfo)
def model_info() -> ModelInfo:
    model, scaler, meta = model_store.load_current()
    active = meta.get("version_id") if meta else None
    return ModelInfo(
        active_version=active,
        registry_size=model_store.registry_size(),
        metrics=meta if meta else None,
    )


@app.get("/models", response_model=ModelListResponse)
def list_models(limit: int = 50, cursor: str | None = None) -> ModelListResponse:
    """List historical models."""
    hist = model_store.get_history(limit, cursor)
    data = []
    for h in hist:
        data.append(ModelVersion(
            version_id=h.get("version_id", "unknown"),
            created_at=h.get("created_at", ""),
            metrics=h.get("metrics"),
            path=h.get("path")
        ))
    
    return ModelListResponse(
        data=data,
        page=PageMetadata(limit=limit, nextCursor=None)
    )


@app.post(
    "/train",
    dependencies=[Depends(require_role("trainer", "admin"))],
    response_model=TrainResponse,
)
def train(req: TrainRequest) -> TrainResponse:
    res = train_once(n_states=req.n_states, tag=req.tag, promote=req.promote)
    meta = res.get("metadata", {})
    version_id = res.get("version_dir", "").split("/")[-1]
    return TrainResponse(
        version_id=version_id or "n/a",
        metric_name=meta.get("metric_name", "val_log_likelihood"),
        metric_value=float(meta.get("metric_value", 0.0)),
        promoted=bool(res.get("promoted", False)),
        message=res.get("message", "ok"),
    )


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> JSONResponse:
    post = predict_proba(req.logret)
    return JSONResponse(post)
