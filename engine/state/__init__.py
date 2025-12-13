"""Runtime state helpers."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

__all__ = [
    "STATE_DIR",
    "SNAP_PATH",
    "SnapshotStore",
    "now_ms",
]

_LOCK = threading.Lock()
STATE_DIR = Path("engine/state")
STATE_DIR.mkdir(parents=True, exist_ok=True)
SNAP_PATH = STATE_DIR / "portfolio.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomic on POSIX
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


def now_ms() -> int:
    return int(time.time() * 1000)


class SnapshotStore:
    """
    Crash-safe portfolio snapshots with Redis backing (and file fallback).
    Schema is intentionally simple and engine-owned:
      {
        "ts_ms": 1712345678901,
        "equity_usd": 12345.67,
        "cash_usd": 12000.12,
        "positions": [
           {"symbol":"BTCUSDT.BINANCE","qty_base":0.0012,"avg_price_quote":62500.5}
        ],
        "pnl":{"realized": 1.23, "unrealized": 0.45},
        "breaker": {"status": "open/closed", "trip_ts": ...}
      }
    """

    def __init__(self, path: Path = SNAP_PATH):
        self.path = path
        self.redis_client = None
        redis_host = os.getenv("REDIS_HOST")
        if redis_host:
            try:
                import redis  # type: ignore
                self.redis_client = redis.Redis(
                    host=redis_host, 
                    port=int(os.getenv("REDIS_PORT", "6379")), 
                    db=0, 
                    decode_responses=True,
                    socket_connect_timeout=2.0
                )
                self.redis_client.ping()
                print(f"[Persistence] Connected to Redis at {redis_host}")
            except Exception as exc:
                print(f"[Persistence] Redis connection failed: {exc}")
                self.redis_client = None

    def load(self) -> dict[str, Any] | None:
        # Try Redis first
        if self.redis_client:
            try:
                data = self.redis_client.get("state:portfolio")
                if data:
                    print("[Persistence] Loaded state from Redis")
                    return json.loads(data)
            except Exception as exc:
                print(f"[Persistence] Failed to load from Redis: {exc}")

        # Fallback to File
        if not self.path.exists():
            return None
        with _LOCK:
            try:
                with open(self.path) as f:
                    print(f"[Persistence] Loaded state from {self.path}")
                    return json.load(f)
            except Exception:
                return None

    def save(self, snapshot: dict[str, Any]) -> None:
        with _LOCK:
            payload = dict(snapshot)
            payload.setdefault("ts_ms", now_ms())
            
            # Save to Redis
            if self.redis_client:
                try:
                    self.redis_client.set("state:portfolio", json.dumps(payload))
                except Exception as exc:
                    # Don't crash on Redis failure, fallback to file is safe
                    pass

            # Always save to File as backup (Double Persistence)
            _atomic_write_json(self.path, payload)
