import time
import threading
import json
import os
import atexit
import signal
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()

CACHE_PATH = Path("engine/state/idempotency_cache.json")


class IdempotencyCache:
    """Simple in-memory cache with TTL to deduplicate order requests."""

    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self.cache: dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> Optional[dict]:
        now = time.time()
        with _LOCK:
            val = self.cache.get(key)
            if not val:
                return None
            ts, data = val
            if now - ts > self.ttl:
                self.cache.pop(key, None)
                return None
            return data

    def set(self, key: str, data: dict):
        with _LOCK:
            self.cache[key] = (time.time(), data)

    def to_dict(self) -> dict[str, dict]:
        """Return non-expired entries for persistence."""
        now = time.time()
        return {
            k: {"ts": ts, "data": data}
            for k, (ts, data) in self.cache.items()
            if now - ts < self.ttl
        }

    def load(self):
        """Load persisted cache on startup."""
        if not CACHE_PATH.exists():
            return
        try:
            data = json.loads(CACHE_PATH.read_text())
            now = time.time()
            for k, v in data.items():
                ts, data = v["ts"], v["data"]
                if now - ts < self.ttl:
                    self.cache[k] = (ts, data)
        except Exception:
            pass  # Silent failure on load

    def save(self):
        """Save cache to disk on shutdown."""
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp = CACHE_PATH.with_suffix(".tmp")
            with open(temp, "w") as f:
                json.dump(self.to_dict(), f)
            os.replace(temp, CACHE_PATH)
        except Exception:
            pass  # Silent failure on save


# Global cache
CACHE = IdempotencyCache()
CACHE.load()


def _flush_cache():
    CACHE.save()


atexit.register(_flush_cache)
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: (_flush_cache(), os._exit(0)))

# --- Audit Logging ---
LOG_DIR = Path("engine/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_jsonl(filename: str, payload: dict):
    path = LOG_DIR / filename
    with _LOCK:
        with open(path, "a") as f:
            f.write(json.dumps(payload, separators=(",", ":")) + "\n")
