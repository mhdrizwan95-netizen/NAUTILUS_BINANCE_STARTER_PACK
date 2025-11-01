from __future__ import annotations

import time
from typing import Dict, Optional


class CooldownTracker:
    """Track per-key cooldown windows.

    The tracker records a unix timestamp until which the key is considered
    active. Expired entries are lazily cleaned on access.
    """

    def __init__(self, cooldown_sec: float) -> None:
        self.cooldown_sec = float(max(0.0, cooldown_sec))
        self._until: Dict[str, float] = {}

    def set(self, key: str, now: Optional[float] = None) -> float:
        """Arm cooldown for `key` and return the expiry timestamp.

        If `cooldown_sec` is 0, the key is considered immediately expired and
        the current time is returned.
        """
        ts = float(now if now is not None else time.time())
        until = ts + self.cooldown_sec
        # Avoid negative/zero until for non-positive cooldowns
        if self.cooldown_sec <= 0:
            until = ts
        self._until[key] = until
        return until

    def active(self, key: str, now: Optional[float] = None) -> bool:
        """Return True if `key` is currently under cooldown."""
        ts = float(now if now is not None else time.time())
        until = self._until.get(key)
        if until is None:
            return False
        if ts >= until:
            # Expired – clean up entry lazily
            try:
                del self._until[key]
            except Exception:
                pass
            return False
        return True

    def remaining(self, key: str, now: Optional[float] = None) -> float:
        """Return remaining cooldown seconds for `key` (0 if inactive)."""
        ts = float(now if now is not None else time.time())
        until = self._until.get(key, 0.0)
        return max(0.0, until - ts)

