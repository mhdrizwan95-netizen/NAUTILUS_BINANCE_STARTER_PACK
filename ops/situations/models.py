from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Predicate(BaseModel):
    feat: str
    op: str
    value: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None


class Situation(BaseModel):
    name: str
    version: int = 1
    window: Dict[str, Any] = Field(default_factory=lambda: {"bars": 20, "interval": "1m"})
    universe: Dict[str, Any] = Field(default_factory=lambda: {"venue": "BINANCE", "quote": "USDT"})
    predicates: List[Predicate] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    risk_template: str = "candidate"
    cooldown_sec: int = 900
    min_depth_usdt: float = 0.0
    priority: float = 0.5
    enabled: bool = True

    class Config:
        extra = "ignore"
