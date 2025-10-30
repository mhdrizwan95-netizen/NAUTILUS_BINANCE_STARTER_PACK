from __future__ import annotations

"""
Announcement → Event Breakout guardrails (publish-only).

Validates late-chase, spread, and 1m notional before relaying to
strategy.event_breakout. If data is unavailable, fails closed.
"""

import os
import time
from typing import Any, Dict


def _as_float(v, d):
    try:
        return float(v)
    except Exception:
        return d


async def _binance_metrics(router, symbol_base: str) -> Dict[str, float]:
    """Fetch minimal metrics: 30m change, spread %, 1m notional.

    Returns dict with keys: {chg_30m, spread_pct, notional_1m}
    """
    # Use venue client if Binance; otherwise return empty
    try:
        client = router.exchange_client()
        if client is None:
            return {}
        # Resolve endpoints based on client capabilities
        # Klines 1m (last 31) to compute 30m change and 1m notional
        kl_fn = getattr(client, "klines", None)
        bt_fn = getattr(client, "book_ticker", None)
        if kl_fn is None or bt_fn is None:
            return {}
        kl = await kl_fn(symbol_base, interval="1m", limit=31)
        if not isinstance(kl, list) or len(kl) < 2:
            return {}
        open0 = _as_float(kl[0][1], None)
        closeN = _as_float(kl[-1][4], None)
        qvol_last = _as_float(kl[-1][7], 0.0)
        if open0 is None or closeN is None or open0 <= 0:
            return {}
        chg_30m = (closeN - open0) / open0
        # Spread
        bt = await bt_fn(symbol_base)
        bid = _as_float(bt.get("bidPrice"), 0.0)
        ask = _as_float(bt.get("askPrice"), 0.0)
        mid = (bid + ask) / 2.0 if bid and ask else 0.0
        spread_pct = abs(ask - bid) / mid if mid else 0.0
        return {"chg_30m": chg_30m, "spread_pct": spread_pct, "notional_1m": qvol_last}
    except Exception:
        return {}


def on_binance_listing(router):
    """Return async handler that relays to strategy.event_breakout when guardrails pass."""
    # Config
    LATE_CHASE = _as_float(os.getenv("LATE_CHASE_PCT_30M", "0.20"), 0.20)
    MAX_SPREAD = _as_float(os.getenv("MAX_SPREAD_PCT", "0.006"), 0.006)
    MIN_NOTIONAL_1M = _as_float(os.getenv("MIN_NOTIONAL_1M_USD", "500000"), 500000.0)
    HALF_MIN = int(_as_float(os.getenv("EVENT_BREAKOUT_HALF_SIZE_MINUTES", "5"), 5))

    allowed_sources = {"binance_announcements", "binance_listings", "listing_sniper_bridge"}

    async def handler(evt: Dict[str, Any]):
        if not isinstance(evt, dict):
            return

        source = str(evt.get("source") or "").strip().lower()
        if source and allowed_sources and source not in allowed_sources:
            return

        payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
        hints = evt.get("asset_hints")
        if isinstance(hints, (str, bytes)):
            hint_list = [hints]
        elif isinstance(hints, (list, tuple, set)):
            hint_list = [str(item) for item in hints if item is not None]
        else:
            hint_list = []
        sym = str(
            payload.get("symbol")
            or (hint_list[0] if hint_list else None)
            or evt.get("symbol")
            or ""
        ).upper()
        if not sym.endswith("USDT"):
            return

        base = sym
        metrics = await _binance_metrics(router, base)
        if not metrics:
            # fail closed if no data
            try:
                from engine import metrics as MET
                MET.event_bo_skips_total.labels(reason="no_klines", symbol=sym).inc()
            except Exception:
                pass
            return
        if metrics["chg_30m"] >= LATE_CHASE:
            try:
                from engine import metrics as MET
                MET.event_bo_skips_total.labels(reason="late_chase", symbol=sym).inc()
            except Exception:
                pass
            return
        if metrics["spread_pct"] >= MAX_SPREAD:
            try:
                from engine import metrics as MET
                MET.event_bo_skips_total.labels(reason="spread", symbol=sym).inc()
            except Exception:
                pass
            return
        if metrics["notional_1m"] < MIN_NOTIONAL_1M:
            try:
                from engine import metrics as MET
                MET.event_bo_skips_total.labels(reason="notional", symbol=sym).inc()
            except Exception:
                pass
            return

        # Half-size window since listing
        half = False
        evt_time = (
            payload.get("time")
            or payload.get("announced_at")
            or evt.get("time")
            or evt.get("announced_at")
        )
        try:
            if evt_time is not None:
                ts_val = float(evt_time)
                if ts_val < 10_000:  # assume seconds -> convert to ms
                    ts_val *= 1000.0
                now = time.time() * 1000.0
                age_min = (float(now) - ts_val) / 60000.0
                half = age_min <= HALF_MIN
        except Exception:
            half = False

        # Relay with meta sizing hint
        from engine.core.event_bus import BUS
        try:
            from engine import metrics as MET
            MET.event_bo_plans_total.labels(venue="BINANCE", symbol=sym, dry="true").inc()
            if half:
                MET.event_bo_half_size_applied_total.labels(symbol=sym).inc()
        except Exception:
            pass
        await BUS.publish("strategy.event_breakout", {"symbol": sym, "reason": "binance_listing", "half_size": bool(half)})

    return handler
