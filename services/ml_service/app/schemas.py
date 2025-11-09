from typing import Any

from pydantic import BaseModel, Field


class TrainRequest(BaseModel):
    n_states: int = Field(default=4, ge=2, le=12)
    tag: str | None = None
    promote: bool = True


class TrainResponse(BaseModel):
    version_id: str
    metric_name: str
    metric_value: float
    promoted: bool
    message: str


class ModelInfo(BaseModel):
    active_version: str | None
    registry_size: int
    metrics: dict[str, Any] | None = None


class PredictRequest(BaseModel):
    logret: list[float] = Field(default_factory=list, description="Series of log returns")


class PredictResponse(BaseModel):
    regime_proba: list[float]
    model_meta: dict[str, Any]
