"""ML Service Schemas."""

from typing import Any
from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """Model information response."""
    active_version: str | None = None
    registry_size: int = 0
    metrics: dict | None = None


class TrainRequest(BaseModel):
    """Training request."""
    n_states: int = Field(default=3, ge=2, le=10)
    tag: str = Field(default="v1")
    promote: bool = Field(default=True)


class TrainResponse(BaseModel):
    """Training response."""
    version_id: str
    metric_name: str
    metric_value: float
    promoted: bool
    message: str


class PredictRequest(BaseModel):
    """Prediction request."""
    logret: list[float] = Field(default_factory=list)


class PredictResponse(BaseModel):
    """Prediction response."""
    probs: list[float] = Field(default_factory=list)
    regime: str = "CHOP"
    confidence: float = 0.0


class ModelVersion(BaseModel):
    """Model version info."""
    version_id: str
    created_at: str
    metrics: dict[str, Any] | None = None
    path: str | None = None


class PageMetadata(BaseModel):
    """Pagination metadata."""
    nextCursor: str | None = None
    prevCursor: str | None = None
    limit: int = 50
    totalHint: int | None = None

class ModelListResponse(BaseModel):
    """Paginated model list."""
    data: list[ModelVersion]
    page: PageMetadata
