from __future__ import annotations
from typing import List, Dict, Any, Optional
from .state import SnapshotStore
try:
    from engine.metrics import REGISTRY as _METRICS
except Exception:
    _METRICS = {}

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
        # Normalize Binance myTrades-style payloads
        sym = t.get("symbol") or t.get("S", "")
        side = "BUY" if bool(t.get("isBuyer", True)) else "SELL"
        qty = float(t.get("qty") if "qty" in t else t.get("quantity", 0.0) or 0.0)
        px = float(t.get("price") or 0.0)
        # Commission may be in non-quote asset; if unknown, treat as 0 for robustness
        fee = 0.0
        try:
            fee = float(
                t.get("quoteFee", 0.0)
                or t.get("commission_quote", 0.0)
                or (t.get("commission", 0.0) if t.get("commissionAsset") in {"USDT", "USD"} else 0.0)
                or 0.0
            )
        except Exception:
            fee = 0.0
        if sym and qty and px:
            # Portfolio.apply_fill expects keyword names: quantity, fee_usd
            portfolio.apply_fill(symbol=sym, side=side, quantity=float(qty), price=float(px), fee_usd=float(fee))
            # Increment venue trades counter for observability
            try:
                ctr = _METRICS.get("venue_trades_total")
                if ctr is not None:
                    ctr.inc()
            except Exception:
                pass

    # Persist new snapshot
    new_snap = portfolio.snapshot()
    store.save(new_snap)
    return new_snap
