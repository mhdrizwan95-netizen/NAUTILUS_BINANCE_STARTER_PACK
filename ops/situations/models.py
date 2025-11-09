from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Predicate(BaseModel):
    feat: str
    op: str
    value: float | None = None
    low: float | None = None
    high: float | None = None


class Situation(BaseModel):
    name: str
    version: int = 1
    window: dict[str, Any] = Field(default_factory=lambda: {"bars": 20, "interval": "1m"})
    universe: dict[str, Any] = Field(default_factory=lambda: {"venue": "BINANCE", "quote": "USDT"})
    predicates: list[Predicate] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    risk_template: str = "candidate"
    cooldown_sec: int = 900
    min_depth_usdt: float = 0.0
    priority: float = 0.5
    enabled: bool = True

    class Config:
        extra = "ignore"
