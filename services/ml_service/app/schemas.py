
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class TrainRequest(BaseModel):
    n_states: int = Field(default=4, ge=2, le=12)
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
