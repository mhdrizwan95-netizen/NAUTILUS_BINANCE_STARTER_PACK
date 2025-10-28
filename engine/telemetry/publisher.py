from __future__ import annotations

<<<<<<< HEAD
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
=======
import logging
import math
import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple, Optional

from ops.deck_metrics import push_metrics, push_strategy_pnl, push_fill

log = logging.getLogger(__name__)

_LAT_SAMPLES: Deque[float] = deque(maxlen=512)
_LAT_LOCK = threading.Lock()

_EQUITY_HISTORY: Deque[Tuple[float, float]] = deque()
_EQUITY_LOCK = threading.Lock()
_EQUITY_PEAK: float = 0.0


def record_latency(latency_ms: float) -> None:
    """Track strategy tick→order latency samples for Deck quantiles."""
    try:
        value = float(latency_ms)
    except (TypeError, ValueError):
        return
    if not math.isfinite(value) or value < 0:
        return
    with _LAT_LOCK:
        _LAT_SAMPLES.append(value)


def latency_quantiles() -> Tuple[float, float]:
    """Return (p50_ms, p95_ms) for recorded latencies."""
    with _LAT_LOCK:
        samples = list(_LAT_SAMPLES)
    if not samples:
        return 0.0, 0.0
    samples.sort()
    return _quantile(samples, 0.5), _quantile(samples, 0.95)


def record_equity(equity_usd: float, *, now: Optional[float] = None) -> Tuple[float, float]:
    """
    Record equity samples for 24h delta + drawdown tracking.

    Returns:
        tuple[pnl_24h, drawdown_pct]
    """
    global _EQUITY_PEAK
    try:
        equity = float(equity_usd)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if not math.isfinite(equity):
        return 0.0, 0.0
    now = now or time.time()
    with _EQUITY_LOCK:
        _EQUITY_HISTORY.append((now, equity))
        cutoff = now - 86400.0
        while _EQUITY_HISTORY and _EQUITY_HISTORY[0][0] < cutoff:
            _EQUITY_HISTORY.popleft()
        baseline = _EQUITY_HISTORY[0][1] if _EQUITY_HISTORY else equity
        pnl_24h = equity - baseline
        _EQUITY_PEAK = max(_EQUITY_PEAK, equity)
        peak = _EQUITY_PEAK or equity
        drawdown_pct = 0.0
        if peak > 0:
            drawdown_pct = max(0.0, (peak - equity) / peak * 100.0)
    return pnl_24h, drawdown_pct
>>>>>>> 9592ab512c66859522d85d5c2e48df7282809b0d


def publish_metrics(
    *,
    equity_usd: float,
    pnl_24h: float,
    drawdown_pct: float,
    positions: int,
    tick_p50_ms: float,
    tick_p95_ms: float,
    error_rate_pct: float,
<<<<<<< HEAD
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
=======
    breaker: Dict[str, object],
    pnl_by_strategy: Optional[Dict[str, float]] = None,
) -> bool:
    """Push metrics to the Deck, optionally including per-strategy PnL."""
    metrics_payload = {
        "equity_usd": float(equity_usd),
        "pnl_24h": float(pnl_24h),
        "drawdown_pct": float(drawdown_pct),
        "positions": int(positions),
        "tick_p50_ms": float(tick_p50_ms),
        "tick_p95_ms": float(tick_p95_ms),
        "error_rate_pct": float(error_rate_pct),
        "breaker": breaker,
    }
    ok = _safe_push(push_metrics, **metrics_payload)
    if pnl_by_strategy:
        _safe_push(push_strategy_pnl, pnl_by_strategy)
    return ok


def publish_fill(fill: Dict) -> bool:
    """Forward a fill payload to the Deck."""
    return _safe_push(push_fill, fill)


def _safe_push(func, *args, **kwargs) -> bool:
    try:
        func(*args, **kwargs)
        return True
    except Exception as exc:  # noqa: broad-except — Deck is optional
        log.debug("Deck push failed: %s", exc)
        return False
>>>>>>> 9592ab512c66859522d85d5c2e48df7282809b0d


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
<<<<<<< HEAD
    pos = (len(values) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    lower_val = values[int(lower)]
    upper_val = values[int(upper)]
    if lower == upper:
        return float(lower_val)
    fraction = pos - lower
    return float(lower_val + (upper_val - lower_val) * fraction)
=======
    idx = (len(values) - 1) * q
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return float(values[lower])
    frac = idx - lower
    return float(values[lower] + (values[upper] - values[lower]) * frac)
>>>>>>> 9592ab512c66859522d85d5c2e48df7282809b0d
