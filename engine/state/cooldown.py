from __future__ import annotations

import time
from collections.abc import Hashable
from dataclasses import dataclass, field


@dataclass
class Cooldowns:
    """Simple TTL-based cooldown tracker."""

    default_ttl: float = 0.0
    _expires: dict[Hashable, float] = field(default_factory=dict)

    def allow(self, key: Hashable, *, now: float | None = None) -> bool:
        """Return True if the cooldown for *key* has elapsed."""
        now_ts = time.time() if now is None else float(now)
        resume_at = self._expires.get(key, 0.0)
        return now_ts >= resume_at

    def hit(self, key: Hashable, *, ttl: float | None = None, now: float | None = None) -> None:
        """Record an action for *key*, starting (or resetting) the cooldown."""
        now_ts = time.time() if now is None else float(now)
        ttl_val = self.default_ttl if ttl is None else max(0.0, float(ttl))
        self._expires[key] = now_ts + ttl_val

    def remaining(self, key: Hashable, *, now: float | None = None) -> float:
        """Return remaining cooldown seconds for *key* (0 when ready)."""
        now_ts = time.time() if now is None else float(now)
        resume_at = self._expires.get(key, 0.0)
        return max(0.0, resume_at - now_ts)

    def clear(self, key: Hashable) -> None:
        """Remove cooldown tracking for *key*."""
        self._expires.pop(key, None)

    def reset(self) -> None:
        """Clear all cooldown tracking."""
        self._expires.clear()
