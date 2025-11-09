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
    Crash-safe portfolio snapshots with atomic writes.
    Schema is intentionally simple and engine-owned:
      {
        "ts_ms": 1712345678901,
        "equity_usd": 12345.67,
        "cash_usd": 12000.12,
        "positions": [
           {"symbol":"BTCUSDT.BINANCE","qty_base":0.0012,"avg_price_quote":62500.5}
        ],
        "pnl":{"realized": 1.23, "unrealized": 0.45}
      }
    """

    def __init__(self, path: Path = SNAP_PATH):
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with _LOCK:
            with open(self.path) as f:
                return json.load(f)

    def save(self, snapshot: dict[str, Any]) -> None:
        with _LOCK:
            payload = dict(snapshot)
            payload.setdefault("ts_ms", now_ms())
            _atomic_write_json(self.path, payload)
