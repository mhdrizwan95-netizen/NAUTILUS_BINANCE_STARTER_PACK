"""SQLite storage for presets and outcomes."""

import json
import sqlite3
from pathlib import Path
from typing import Any


_conn_cache: dict[str, sqlite3.Connection] = {}


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Get or create connection to database."""
    if db_path not in _conn_cache:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _conn_cache[db_path] = conn
    return _conn_cache[db_path]


def init(db_path: str) -> None:
    """Initialize database schema."""
    conn = _get_conn(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS presets (
            strategy TEXT NOT NULL,
            instrument TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            params TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (strategy, instrument, preset_id)
        );
        
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            instrument TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            reward REAL NOT NULL,
            features TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_outcomes_lookup 
            ON outcomes(strategy, instrument);
    """)
    conn.commit()


def upsert_preset(
    db_path: str,
    strategy: str,
    instrument: str,
    preset_id: str,
    params: dict[str, Any],
) -> None:
    """Insert or update a preset configuration."""
    conn = _get_conn(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO presets (strategy, instrument, preset_id, params)
           VALUES (?, ?, ?, ?)""",
        (strategy, instrument, preset_id, json.dumps(params)),
    )
    conn.commit()


def list_presets(
    db_path: str,
    strategy: str,
    instrument: str,
) -> list[tuple[str, dict[str, Any]]]:
    """List all presets for a strategy/instrument pair.
    
    Returns:
        List of (preset_id, params) tuples
    """
    conn = _get_conn(db_path)
    cursor = conn.execute(
        """SELECT preset_id, params FROM presets
           WHERE strategy = ? AND instrument = ?
           ORDER BY preset_id""",
        (strategy, instrument),
    )
    return [(row["preset_id"], json.loads(row["params"])) for row in cursor]


def log_outcome(
    db_path: str,
    strategy: str,
    instrument: str,
    preset_id: str,
    reward: float,
    features: dict[str, float] | None = None,
) -> None:
    """Log an outcome (reward) for a preset selection."""
    conn = _get_conn(db_path)
    conn.execute(
        """INSERT INTO outcomes (strategy, instrument, preset_id, reward, features)
           VALUES (?, ?, ?, ?, ?)""",
        (strategy, instrument, preset_id, reward, json.dumps(features or {})),
    )
    conn.commit()


def fetch_outcomes(
    db_path: str,
    strategy: str,
    instrument: str,
    limit: int = 1000,
) -> list[tuple[str, float, dict[str, float]]]:
    """Fetch historical outcomes for bandit training.
    
    Returns:
        List of (preset_id, reward, features) tuples
    """
    conn = _get_conn(db_path)
    cursor = conn.execute(
        """SELECT preset_id, reward, features FROM outcomes
           WHERE strategy = ? AND instrument = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (strategy, instrument, limit),
    )
    return [
        (row["preset_id"], row["reward"], json.loads(row["features"] or "{}"))
        for row in cursor
    ]


def get_preset(
    db_path: str,
    strategy: str,
    instrument: str,
    preset_id: str,
) -> dict[str, Any] | None:
    """Get a specific preset by ID."""
    conn = _get_conn(db_path)
    cursor = conn.execute(
        """SELECT params FROM presets
           WHERE strategy = ? AND instrument = ? AND preset_id = ?""",
        (strategy, instrument, preset_id),
    )
    row = cursor.fetchone()
    return json.loads(row["params"]) if row else None


def delete_preset(
    db_path: str,
    strategy: str,
    instrument: str,
    preset_id: str,
) -> bool:
    """Delete a preset."""
    conn = _get_conn(db_path)
    cursor = conn.execute(
        """DELETE FROM presets
           WHERE strategy = ? AND instrument = ? AND preset_id = ?""",
        (strategy, instrument, preset_id),
    )
    conn.commit()
    return cursor.rowcount > 0
