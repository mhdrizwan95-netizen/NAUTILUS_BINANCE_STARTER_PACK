"""Pydantic models for normalized engine events."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ExternalEvent(BaseModel):
    """Normalized envelope for external (off-tick) signals."""

    source: str = Field(..., description="Producer identifier, e.g. binance_announcements")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Raw event payload")
    id: Optional[str] = Field(default=None, description="Stable identifier for idempotency")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Event timestamp")
    meta: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata (priority, expires_at, etc.)")

    def with_default_id(self) -> "ExternalEvent":
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
