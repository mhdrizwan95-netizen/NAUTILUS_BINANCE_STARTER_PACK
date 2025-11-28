from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DB = None
_LOCK = threading.Lock()
_Q: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
_RETENTION_MS = 7 * 24 * 60 * 60 * 1000  # seven days in ms
_CLEANUP_INTERVAL_SEC = 6 * 60 * 60  # sweep every 6 hours
_LOGGER = logging.getLogger(__name__)


def _conn(db_path: str) -> sqlite3.Connection:
    global _DB
    if _DB is None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # Increase busy timeout to reduce 'database is locked' errors under WAL
        _DB = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
        _DB.execute("PRAGMA journal_mode=WAL")
        _DB.execute("PRAGMA busy_timeout=5000")
    return _DB


def init(db_path="data/runtime/trades.db", schema="engine/storage/schema.sql"):
    con = _conn(db_path)
    with open(schema, encoding="utf-8") as f:
        con.executescript(f.read())
    con.commit()
    # background flusher
    t = threading.Thread(target=_flush_loop, args=(con,), daemon=True)
    t.start()
    cleaner = threading.Thread(target=_cleanup_loop, args=(con,), daemon=True)
    cleaner.start()


def _flush_loop(con: sqlite3.Connection):
    batch = []
    last = time.time()
    while True:
        try:
            sql, params = _Q.get(timeout=0.25)
            batch.append((sql, params))
        except queue.Empty:
            pass
        if batch and (len(batch) >= 64 or time.time() - last > 0.5):
            with _LOCK:
                (
                    con.executemany(batch[0][0], [p for _, p in batch])
                    if len({sql for sql, _ in batch}) == 1
                    else [con.execute(sql, p) for sql, p in batch]
                )
                con.commit()
            batch.clear()
            last = time.time()


def enqueue(sql: str, params: tuple[Any, ...]):
    _Q.put((sql, params))


def _cleanup_loop(con: sqlite3.Connection):
    """Periodically prune old rows and VACUUM to keep disk bounded."""
    while True:
        cutoff_ms = int(time.time() * 1000) - _RETENTION_MS
        try:
            with _LOCK:
                con.execute("DELETE FROM orders WHERE ts_update < ?", (cutoff_ms,))
                con.execute("DELETE FROM fills WHERE ts < ?", (cutoff_ms,))
                con.execute("DELETE FROM equity_snapshots WHERE ts < ?", (cutoff_ms,))
                con.commit()
                con.execute("VACUUM")
        except sqlite3.Error as exc:
            _LOGGER.warning("sqlite cleanup failed: %s", exc, exc_info=True)
        time.sleep(_CLEANUP_INTERVAL_SEC)


# convenience wrappers
def insert_order(d: dict[str, Any]):
    enqueue(
        """INSERT OR REPLACE INTO orders(id,venue,symbol,side,qty,price,status,ts_accept,ts_update)
               VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            d["id"],
            d["venue"],
            d["symbol"],
            d["side"],
            d["qty"],
            d.get("price"),
            d["status"],
            d["ts_accept"],
            d["ts_update"],
        ),
    )


def insert_fill(d: dict[str, Any]):
    enqueue(
        """INSERT OR REPLACE INTO fills(id,order_id,venue,symbol,side,qty,price,fee_ccy,fee,ts)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            d["id"],
            d["order_id"],
            d["venue"],
            d["symbol"],
            d["side"],
            d["qty"],
            d["price"],
            d.get("fee_ccy"),
            d.get("fee"),
            d["ts"],
        ),
    )


def upsert_position(venue: str, symbol: str, net_qty: float, avg_price: float | None, ts_ms: int):
    enqueue(
        """INSERT INTO positions(venue,symbol,net_qty,avg_price,updated_ms)
               VALUES(?,?,?,?,?)
               ON CONFLICT(venue,symbol) DO UPDATE SET
               net_qty=excluded.net_qty, avg_price=excluded.avg_price, updated_ms=excluded.updated_ms""",
        (venue, symbol, net_qty, avg_price, ts_ms),
    )


def insert_equity(venue: str, equity: float, cash: float, upnl: float, ts_ms: int):
    enqueue(
        """INSERT OR REPLACE INTO equity_snapshots(venue,equity_usd,cash_usd,upnl_usd,ts)
               VALUES(?,?,?,?,?)""",
        (venue, equity, cash, upnl, ts_ms),
    )
