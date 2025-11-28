import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
DB_PATH = Path("engine/state/idempotency.sqlite")


class IdempotencyCache:
    """Persistent SQLite-backed cache to deduplicate order requests."""

    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self._init_db()

    def _init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idempotency (
                        key TEXT PRIMARY KEY,
                        data TEXT,
                        created_at REAL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON idempotency(created_at)")
                conn.commit()

    def get(self, key: str) -> dict | None:
        now = time.time()
        cutoff = now - self.ttl
        with _LOCK:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.execute(
                        "SELECT data FROM idempotency WHERE key = ? AND created_at > ?",
                        (key, cutoff),
                    )
                    row = cursor.fetchone()
                    if row:
                        return json.loads(row[0])
            except sqlite3.Error:
                logging.exception("Idempotency cache read failed")
        return None

    def set(self, key: str, data: dict):
        now = time.time()
        json_data = json.dumps(data)
        with _LOCK:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO idempotency (key, data, created_at) VALUES (?, ?, ?)",
                        (key, json_data, now),
                    )
                    conn.commit()
            except sqlite3.Error:
                logging.exception("Idempotency cache write failed")

    def cleanup(self):
        """Remove expired entries."""
        now = time.time()
        cutoff = now - self.ttl
        with _LOCK:
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("DELETE FROM idempotency WHERE created_at <= ?", (cutoff,))
                    conn.commit()
            except sqlite3.Error:
                logging.exception("Idempotency cache cleanup failed")


# Global cache
CACHE = IdempotencyCache()

# --- Audit Logging ---
LOG_DIR = Path("engine/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_jsonl(filename: str, payload: dict):
    path = LOG_DIR / filename
    with _LOCK:
        with open(path, "a") as f:
            f.write(json.dumps(payload, separators=(",", ":")) + "\n")
