from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any

from .state import SnapshotStore

logger = logging.getLogger(__name__)

try:
    from engine.metrics import REGISTRY as _METRICS
except ImportError:
    _METRICS = {}

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    asyncio.TimeoutError,
)
_STORE_ERRORS = _SUPPRESSIBLE_EXCEPTIONS + (ImportError,)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


class ExchangeClientProto:
    """Tiny protocol the real client should satisfy."""

    def my_trades_since(self, symbol: str, start_ms: int) -> list[dict[str, Any]]:
        raise NotImplementedError


class PortfolioProto:
    """Expected minimal interface of your portfolio service."""

    def apply_fill(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee_usd: float = 0.0,
        ts_ms: int = 0,
        venue: str | None = None,
        market: str | None = None,
    ) -> None:
        raise NotImplementedError

    def snapshot(self) -> dict:
        raise NotImplementedError


def reconcile_since_snapshot(
    *, portfolio: PortfolioProto, client: ExchangeClientProto, symbols: list[str]
) -> dict:
    """
    Idempotent: loads the last snapshot timestamp, fetches fills since then for each symbol,
    applies them in chronological order, and returns the updated snapshot.
    """
    snapshot_store = SnapshotStore()
    snap = snapshot_store.load()
    start_ms = (snap or {}).get("ts_ms", 0)

    # Collect trades across symbols
    trades: list[dict[str, Any]] = []
    for s in symbols:
        try:
            result = client.my_trades_since(s, start_ms)
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    result = asyncio.run(result)
                else:
                    result = asyncio.run_coroutine_threadsafe(result, loop).result()
            trades.extend(result or [])
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed(f"reconcile fetch for {s}", exc)
            continue
    trades.sort(key=lambda t: t.get("time", 0))

    # Apply fills
    for t in trades:
        # Normalize Binance myTrades-style payloads
        sym = t.get("symbol") or t.get("S", "")
        side = "BUY" if bool(t.get("isBuyer", True)) else "SELL"
        qty_str = str(t.get("qty") if "qty" in t else t.get("quantity", "0.0") or "0.0")
        px_str = str(t.get("price", "0.0") or "0.0")
        qty = float(qty_str)
        px = float(px_str)
        # Commission may be in non-quote asset; if unknown, treat as 0 for robustness
        fee = 0.0
        try:
            fee = float(
                t.get("quoteFee", 0.0)
                or t.get("commission_quote", 0.0)
                or (
                    t.get("commission", 0.0) if t.get("commissionAsset") in {"USDT", "USD"} else 0.0
                )
                or 0.0
            )
        except (TypeError, ValueError):
            fee = 0.0
        if sym and qty and px:
            venue_hint = str(t.get("venue") or "BINANCE").upper()
            market_hint = str(t.get("market") or t.get("isIsolated") or "").strip().lower()
            if market_hint not in {"margin", "spot", "futures", "options"}:
                market_hint = None
            qualified_symbol = sym if "." in sym else f"{sym}.{venue_hint}" if venue_hint else sym
            # Portfolio.apply_fill expects keyword names: quantity, fee_usd
            portfolio.apply_fill(
                symbol=qualified_symbol,
                side=side,
                quantity=float(qty),
                price=float(px),
                fee_usd=float(fee),
                venue=venue_hint,
                market=market_hint,
            )
            # Store fill persistently
            try:
                from engine.storage import sqlite as store

                store.insert_fill(
                    {
                        "id": t.get("id", str(int(time.time() * 1000000))),
                        "order_id": t.get("orderId", ""),
                        "venue": "binance",  # Assuming Binance for now; could be venue-agnostic later
                        "symbol": sym,
                        "side": side,
                        "qty": qty,
                        "price": px,
                        "fee_ccy": "USDT" if fee > 0 else None,
                        "fee": fee,
                        "ts": int(time.time() * 1000),
                    }
                )
            except _STORE_ERRORS as exc:
                _log_suppressed("reconcile store insert", exc)
            # Increment venue trades counter for observability
            try:
                ctr = _METRICS.get("venue_trades_total")
                if ctr is not None:
                    ctr.inc()
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("reconcile metrics increment", exc)

    # Persist new snapshot
    new_snap = portfolio.snapshot()
    snapshot_store.save(new_snap)
    return new_snap
