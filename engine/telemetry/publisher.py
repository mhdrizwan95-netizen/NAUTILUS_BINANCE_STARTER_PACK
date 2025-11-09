from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from threading import Lock

log = logging.getLogger(__name__)

_LAT_SAMPLES: deque[float] = deque(maxlen=512)
_LAT_LOCK = threading.Lock()
_LAST_LATENCY_BY_SYMBOL: dict[str, float] = {}

_EQUITY_HISTORY: deque[tuple[float, float]] = deque()
_EQUITY_LOCK = threading.Lock()
_EQUITY_PEAK: float = 0.0

_PNL_LOCK = Lock()
_PNL_WINDOW: deque[tuple[float, float]] = deque()


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(ordered[lower])
    frac = pos - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * frac)


def record_latency(latency_ms: float) -> None:
    try:
        value = float(latency_ms)
    except (TypeError, ValueError):
        return
    if value < 0 or not math.isfinite(value):
        return
    with _LAT_LOCK:
        _LAT_SAMPLES.append(value)


def latency_quantiles() -> tuple[float, float]:
    with _LAT_LOCK:
        samples = list(_LAT_SAMPLES)
    if not samples:
        return 0.0, 0.0
    samples.sort()
    return _quantile(samples, 0.5), _quantile(samples, 0.95)


def latency_percentiles() -> tuple[float, float]:
    return latency_quantiles()


def record_tick_latency(symbol: str, latency_ms: float) -> None:
    try:
        value = float(latency_ms)
    except (TypeError, ValueError):
        return
    if value < 0 or not math.isfinite(value):
        return
    canonical_keys = {symbol.upper()}
    if "." in symbol:
        canonical_keys.add(symbol.split(".")[0].upper())
    with _LAT_LOCK:
        _LAT_SAMPLES.append(value)
        for key in canonical_keys:
            _LAST_LATENCY_BY_SYMBOL[key] = value


def consume_latency(symbol: str) -> float | None:
    keys = [symbol.upper()]
    if "." not in symbol:
        keys.append(f"{symbol.upper()}.BINANCE")
    with _LAT_LOCK:
        for key in keys:
            value = _LAST_LATENCY_BY_SYMBOL.pop(key, None)
            if value is not None:
                return value
    return None


def record_equity(equity_usd: float, *, now: float | None = None) -> tuple[float, float]:
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


def record_realized_total(realized_total_usd: float) -> float:
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


# Legacy compatibility: previously forwarded metrics to the Deck API.
# With the Command Center running inside the Ops service, these become no-ops.
def publish_metrics(**_kwargs: dict[str, object]) -> None:
    return None


def publish_fill(_fill: dict) -> None:
    return None
