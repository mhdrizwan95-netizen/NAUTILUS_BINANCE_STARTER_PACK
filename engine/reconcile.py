from __future__ import annotations
from typing import List, Dict, Any, Optional
from .state import SnapshotStore

class ExchangeClientProto:
    """Tiny protocol the real client should satisfy."""
    def my_trades_since(self, symbol: str, start_ms: int) -> List[Dict[str, Any]]:
        raise NotImplementedError

class PortfolioProto:
    """Expected minimal interface of your portfolio service."""
    def apply_fill(self, *, symbol: str, side: str, qty: float, price: float, fee_quote: float=0.0, ts_ms: int=0) -> None:
        raise NotImplementedError
    def snapshot(self) -> dict:
        raise NotImplementedError

def reconcile_since_snapshot(*, portfolio: PortfolioProto, client: ExchangeClientProto, symbols: List[str]) -> dict:
    """
    Idempotent: loads the last snapshot timestamp, fetches fills since then for each symbol,
    applies them in chronological order, and returns the updated snapshot.
    """
    store = SnapshotStore()
    snap = store.load()
    start_ms = (snap or {}).get("ts_ms", 0)

    # Collect trades across symbols
    trades: List[Dict[str, Any]] = []
    for s in symbols:
        try:
            trades.extend(client.my_trades_since(s, start_ms))
        except Exception:
            # Best-effort: skip symbol on API error; can log if needed
            continue
    trades.sort(key=lambda t: t.get("time", 0))

    # Apply fills
    for t in trades:
        portfolio.apply_fill(
            symbol=t["symbol"],
            side=t.get("isBuyer", True) and "BUY" or "SELL",
            qty=float(t["qty"] if "qty" in t else t.get("quantity", 0.0)),
            price=float(t["price"]),
            fee_quote=float(t.get("quoteFee", 0.0) or t.get("commission_quote", 0.0) or 0.0),
            ts_ms=int(t.get("time", 0))
        )

    # Persist new snapshot
    new_snap = portfolio.snapshot()
    store.save(new_snap)
    return new_snap
