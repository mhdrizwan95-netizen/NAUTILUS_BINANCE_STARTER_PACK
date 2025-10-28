from __future__ import annotations

import math
import time
from collections import deque
from threading import Lock
from typing import Dict, Optional

from ops.deck_metrics import push_fill, push_metrics, push_strategy_pnl

# Shared buffers for latency and realized PnL windows
_LAT_LOCK = Lock()
_LAT_SAMPLES = deque(maxlen=400)
_LAST_LATENCY_BY_SYMBOL: Dict[str, float] = {}

_PNL_LOCK = Lock()
_PNL_WINDOW = deque()  # (ts, realized_total)


def publish_metrics(
    *,
    equity_usd: float,
    pnl_24h: float,
    drawdown_pct: float,
    positions: int,
    tick_p50_ms: float,
    tick_p95_ms: float,
    error_rate_pct: float,
    breaker: Dict[str, bool],
    pnl_by_strategy: Optional[Dict[str, float]] = None,
) -> None:
    """Push core engine metrics and optional strategy PnL snapshot to the Deck."""
    push_metrics(
        equity_usd=equity_usd,
        pnl_24h=pnl_24h,
        drawdown_pct=drawdown_pct,
        tick_p50_ms=tick_p50_ms,
        tick_p95_ms=tick_p95_ms,
        error_rate_pct=error_rate_pct,
        positions=positions,
        breaker=breaker,
    )
    if pnl_by_strategy:
        push_strategy_pnl(pnl_by_strategy)


def publish_fill(fill: Dict) -> None:
    """Forward a fill/trade event to the Deck."""
    push_fill(fill)


def record_tick_latency(symbol: str, latency_ms: float) -> None:
    """Store tick→order latency samples for percentile reporting."""
    if latency_ms is None:
        return
    try:
        latency_val = float(latency_ms)
        if latency_val < 0:
            return
    except (TypeError, ValueError):
        return
    canonical_keys = {symbol.upper()}
    if "." in symbol:
        canonical_keys.add(symbol.split(".")[0].upper())
    with _LAT_LOCK:
        _LAT_SAMPLES.append(latency_val)
        for key in canonical_keys:
            _LAST_LATENCY_BY_SYMBOL[key] = latency_val


def consume_latency(symbol: str) -> Optional[float]:
    """Fetch and clear the most recent latency recorded for a symbol (best-effort)."""
    keys = [symbol.upper()]
    if "." not in symbol:
        keys.append(f"{symbol.upper()}.BINANCE")  # common default
    with _LAT_LOCK:
        for key in keys:
            val = _LAST_LATENCY_BY_SYMBOL.pop(key, None)
            if val is not None:
                return val
    return None


def latency_percentiles() -> tuple[float, float]:
    """Return (p50, p95) latency in milliseconds from recent samples."""
    with _LAT_LOCK:
        samples = list(_LAT_SAMPLES)
    if not samples:
        return 0.0, 0.0
    samples.sort()
    return _quantile(samples, 0.5), _quantile(samples, 0.95)


def record_realized_total(realized_total_usd: float) -> float:
    """Track realized PnL history and return trailing 24h delta."""
    try:
        total = float(realized_total_usd)
    except (TypeError, ValueError):
        return 0.0
    now = time.time()
    cutoff = now - 86400.0
    with _PNL_LOCK:
        _PNL_WINDOW.append((now, total))
        while _PNL_WINDOW and _PNL_WINDOW[0][0] < cutoff:
            _PNL_WINDOW.popleft()
        anchor = _PNL_WINDOW[0][1] if _PNL_WINDOW else total
    return total - anchor


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    lower_val = values[int(lower)]
    upper_val = values[int(upper)]
    if lower == upper:
        return float(lower_val)
    fraction = pos - lower
    return float(lower_val + (upper_val - lower_val) * fraction)
