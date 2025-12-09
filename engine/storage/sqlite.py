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


# =============================
# Query functions for analytics
# =============================

def get_recent_fills(limit: int = 500) -> list[dict[str, Any]]:
    """Fetch recent fills for trade history and metrics computation."""
    global _DB
    if _DB is None:
        return []
    try:
        with _LOCK:
            cursor = _DB.execute(
                """SELECT id, order_id, venue, symbol, side, qty, price, fee_ccy, fee, ts
                   FROM fills ORDER BY ts DESC LIMIT ?""",
                (limit,),
            )
            rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "order_id": r[1],
                "venue": r[2],
                "symbol": r[3],
                "side": r[4],
                "qty": r[5],
                "price": r[6],
                "fee_ccy": r[7],
                "fee": r[8],
                "ts": r[9],
            }
            for r in rows
        ]
    except sqlite3.Error as exc:
        _LOGGER.warning("get_recent_fills failed: %s", exc)
        return []


def get_equity_curve(limit: int = 100) -> list[dict[str, Any]]:
    """Fetch equity snapshots for drawdown calculation."""
    global _DB
    if _DB is None:
        return []
    try:
        with _LOCK:
            cursor = _DB.execute(
                """SELECT venue, equity_usd, cash_usd, upnl_usd, ts
                   FROM equity_snapshots ORDER BY ts DESC LIMIT ?""",
                (limit,),
            )
            rows = cursor.fetchall()
        return [
            {
                "venue": r[0],
                "equity_usd": r[1],
                "cash_usd": r[2],
                "upnl_usd": r[3],
                "ts": r[4],
            }
            for r in rows
        ]
    except sqlite3.Error as exc:
        _LOGGER.warning("get_equity_curve failed: %s", exc)
        return []


def compute_trade_stats() -> dict[str, float]:
    """Compute win rate and returns for Sharpe calculation from fills.
    
    Returns:
        dict with 'win_rate', 'total_trades', 'returns' (list of % returns per round-trip)
    """
    fills = get_recent_fills(limit=1000)
    if not fills:
        return {"win_rate": 0.0, "total_trades": 0, "returns": [], "max_drawdown": 0.0}
    
    # Group fills by symbol to compute round-trip PnL
    from collections import defaultdict
    positions: dict[str, list[dict]] = defaultdict(list)
    for fill in sorted(fills, key=lambda x: x["ts"]):
        positions[fill["symbol"]].append(fill)
    
    round_trips = []
    for symbol, sym_fills in positions.items():
        net_qty = 0.0
        avg_entry = 0.0
        for fill in sym_fills:
            qty_signed = fill["qty"] if fill["side"] == "BUY" else -fill["qty"]
            if net_qty == 0:
                # Opening position
                net_qty = qty_signed
                avg_entry = fill["price"]
            elif (net_qty > 0 and qty_signed < 0) or (net_qty < 0 and qty_signed > 0):
                # Closing or reducing position
                closed_qty = min(abs(net_qty), abs(qty_signed))
                if net_qty > 0:
                    # Was long, sold to close
                    pnl_pct = ((fill["price"] - avg_entry) / avg_entry) * 100 if avg_entry > 0 else 0
                else:
                    # Was short, bought to close
                    pnl_pct = ((avg_entry - fill["price"]) / avg_entry) * 100 if avg_entry > 0 else 0
                round_trips.append(pnl_pct)
                net_qty += qty_signed
                if abs(net_qty) < 1e-10:
                    net_qty = 0.0
                    avg_entry = 0.0
            else:
                # Adding to position - update average
                total_cost = avg_entry * abs(net_qty) + fill["price"] * abs(qty_signed)
                net_qty += qty_signed
                avg_entry = total_cost / abs(net_qty) if net_qty != 0 else 0
    
    if not round_trips:
        return {"win_rate": 0.0, "total_trades": 0, "returns": [], "max_drawdown": 0.0}
    
    wins = sum(1 for r in round_trips if r > 0)
    win_rate = wins / len(round_trips) * 100 if round_trips else 0.0
    
    # Compute max drawdown from equity curve
    equity_curve = get_equity_curve(limit=500)
    max_dd = 0.0
    if equity_curve:
        equities = [e["equity_usd"] for e in reversed(equity_curve) if e["equity_usd"] > 0]
        if equities:
            peak = equities[0]
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
    
    return {
        "win_rate": round(win_rate, 2),
        "total_trades": len(round_trips),
        "returns": round_trips,
        "max_drawdown": round(max_dd, 2),
    }

