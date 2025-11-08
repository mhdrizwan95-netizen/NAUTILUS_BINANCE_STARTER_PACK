import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)
DEFAULT_DB = os.environ.get("LEDGER_DB", "/shared/manifest.sqlite")

DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS files(
  file_id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  t_start INTEGER NOT NULL,
  t_end INTEGER NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  size_bytes INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('downloaded','processing','processed','deleted')),
  created_at REAL NOT NULL,
  processed_at REAL,
  deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_time ON files(symbol, timeframe, t_start, t_end);

CREATE TABLE IF NOT EXISTS watermarks(
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS locks(
  name TEXT PRIMARY KEY,
  owner TEXT,
  ts REAL
);
"""


def _connect(db_path: str = DEFAULT_DB):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init(db_path: str = DEFAULT_DB):
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        for stmt in DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        conn.commit()
    finally:
        conn.close()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register_file(
    path: str,
    symbol: str,
    timeframe: str,
    t_start: int,
    t_end: int,
    db_path: str = DEFAULT_DB,
) -> Tuple[str, bool]:
    """
    Register a downloaded file. Returns (file_id, inserted_new: bool).
    If a file with same content (sha256) already exists, we don't duplicate entries.
    """
    st = os.stat(path)
    sha = sha256_file(path)
    file_id = sha
    now = time.time()
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
          INSERT OR IGNORE INTO files(file_id, path, symbol, timeframe, t_start, t_end, sha256, size_bytes, status, created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
            (
                file_id,
                path,
                symbol,
                timeframe,
                int(t_start),
                int(t_end),
                sha,
                st.st_size,
                "downloaded",
                now,
            ),
        )
        conn.commit()
        inserted = cur.rowcount > 0
        return file_id, inserted
    finally:
        conn.close()


def claim_unprocessed(limit: int = 50, db_path: str = DEFAULT_DB) -> list:
    """
    Atomically claim up to 'limit' downloaded files for processing.
    Returns the rows (dicts).
    """
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT file_id FROM files WHERE status='downloaded' ORDER BY t_start ASC LIMIT ?",
            (limit,),
        )
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            conn.commit()
            return []
        cur.execute(
            f"UPDATE files SET status='processing' WHERE file_id IN ({','.join(['?']*len(ids))})",
            ids,
        )
        conn.commit()
        # fetch details
        cur.execute(f"SELECT * FROM files WHERE file_id IN ({','.join(['?']*len(ids))})", ids)
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


def mark_processed(file_id: str, delete_file: bool = True, db_path: str = DEFAULT_DB):
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE files SET status='processed', processed_at=? WHERE file_id=?",
            (time.time(), file_id),
        )
        conn.commit()
    finally:
        conn.close()
    # delete from filesystem after marking processed
    if delete_file:
        _delete_file_by_id(file_id, db_path)


def requeue(file_ids: List[str], db_path: str = DEFAULT_DB):
    if not file_ids:
        return
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(file_ids))
        cur.execute(
            f"UPDATE files SET status='downloaded', processed_at=NULL, deleted_at=NULL WHERE file_id IN ({placeholders}) AND status='processing'",
            file_ids,
        )
        conn.commit()
    finally:
        conn.close()


def _delete_file_by_id(file_id: str, db_path: str = DEFAULT_DB):
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT path FROM files WHERE file_id=?", (file_id,))
        row = cur.fetchone()
        if row:
            path = row[0]
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                logger.warning(
                    "Failed to remove %s for file_id=%s: %s", path, file_id, exc, exc_info=True
                )
            cur.execute(
                "UPDATE files SET status='deleted', deleted_at=? WHERE file_id=?",
                (time.time(), file_id),
            )
            conn.commit()
    finally:
        conn.close()


def set_watermark(name: str, value: int, db_path: str = DEFAULT_DB):
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO watermarks(name, value) VALUES(?, ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, int(value)),
        )
        conn.commit()
    finally:
        conn.close()


def get_watermark(
    name: str, default: Optional[int] = None, db_path: str = DEFAULT_DB
) -> Optional[int]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM watermarks WHERE name=?", (name,))
        row = cur.fetchone()
        return int(row[0]) if row else default
    finally:
        conn.close()
