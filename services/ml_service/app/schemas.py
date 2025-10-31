from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class TrainRequest(BaseModel):
    n_states: int = Field(default=4, ge=2, le=12)
    window_days: int = Field(default=365, ge=30, le=1460)
    tag: Optional[str] = None
    promote: bool = True


class TrainResponse(BaseModel):
    version_id: str
    metric_name: str
    metric_value: float
    promoted: bool
    message: str


class ModelInfo(BaseModel):
    active_version: Optional[str]
    registry_size: int
    metrics: Optional[Dict[str, Any]] = None
