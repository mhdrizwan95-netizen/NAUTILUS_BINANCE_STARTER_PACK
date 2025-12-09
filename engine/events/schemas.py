"""Pydantic models for normalized engine events."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ExternalEvent(BaseModel):
    """Normalized envelope for external (off-tick) signals."""

    source: str = Field(..., description="Producer identifier, e.g. binance_listings")
    payload: dict[str, Any] = Field(default_factory=dict, description="Raw event payload")
    id: str | None = Field(default=None, description="Stable identifier for idempotency")
    ts: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event timestamp",
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata (priority, expires_at, etc.)",
    )

    def with_default_id(self) -> ExternalEvent:
        """Populate ``id`` if missing using a deterministic hash."""

        if self.id:
            return self
        basis = {
            "source": self.source,
            "payload": self.payload,
            "ts": int(self.ts.timestamp()),
        }
        digest = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]
        self.id = f"{self.source}:{digest}"
        return self


class LiquidationEvent(BaseModel):
    """Normalized liquidation event (forced order)."""

    symbol: str
    side: str
    price: float
    quantity: float
    quantity_filled: float = 0.0
    notional: float = 0.0
    ts: float
    venue: str = "BINANCE"
    source: str = "binance_force_order"

