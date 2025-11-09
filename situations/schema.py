from __future__ import annotations

from pydantic import BaseModel


class Predicate(BaseModel):
    feat: str
    op: str
    value: float | None = None
    low: float | None = None
    high: float | None = None


class Situation(BaseModel):
    name: str
    version: int
    window: dict
    predicates: list[Predicate]
    cooldown_sec: int = 600
    min_depth_usdt: float = 0.0
    priority: float = 0.5
