import time
from typing import Dict

class Cooldowns:
    def __init__(self, default_ttl: float = 0.0):
        self.default_ttl = default_ttl
        self._cooldowns: Dict[str, float] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        return now >= self._cooldowns.get(key, 0.0)

    def hit(self, key: str, ttl: float | None = None, now: float | None = None) -> None:
        if now is None:
            now = time.time()
        if ttl is None:
            ttl = self.default_ttl
        self._cooldowns[key] = now + ttl

    def remaining(self, key: str, now: float | None = None) -> float:
        if now is None:
            now = time.time()
        expiry = self._cooldowns.get(key, 0.0)
        return max(0.0, expiry - now)
