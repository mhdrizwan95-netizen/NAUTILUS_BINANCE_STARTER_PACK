from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class Predicate(BaseModel):
    feat: str
    op: str
    value: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None


class Situation(BaseModel):
    name: str
    version: int
    window: dict
    predicates: List[Predicate]
    cooldown_sec: int = 600
    min_depth_usdt: float = 0.0
    priority: float = 0.5
