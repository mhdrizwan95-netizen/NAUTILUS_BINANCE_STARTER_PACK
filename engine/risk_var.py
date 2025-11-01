from __future__ import annotations

"""
VAR estimation utilities (stop-aware with ATR fallback when available).

Designed to work with the existing Portfolio.Position objects (which have
fields: symbol, quantity, avg_price, last_price). If a position exposes
`stop` or `entry` attributes, they will be used preferentially.

`md` parameter is optional and may provide `atr(symbol, tf, n)`.
If md is missing or ATR unavailable, we fall back to notional risk.
"""

from typing import Iterable, Any, List


def _get(attr: str, obj: Any, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def estimate_var_usd(
    position: Any,
    md: Any | None = None,
    tf: str = "5m",
    n: int = 14,
    *,
    use_stop_first: bool = True,
) -> float:
    qty = float(abs(_get("quantity", position, 0.0)) or 0.0)
    if qty <= 0:
        return 0.0

    # Prefer stop-distance if available
    if use_stop_first:
        entry = _get("entry", position, None)
        if entry is None:
            entry = _get("avg_price", position, None)
        stop = _get("stop", position, None)
        try:
            if entry is not None and stop is not None:
                return abs(float(entry) - float(stop)) * qty
        except Exception:
            pass

    # ATR fallback if provided
    if md is not None:
        try:
            atr_val = md.atr(_get("symbol", position, ""), tf=tf, n=n)
            if isinstance(atr_val, (int, float)) and atr_val > 0:
                return float(atr_val) * qty
            # Zero/None ATR → 1% notional proxy for total ordering
            last = _get("last_price", position, None)
            if last is None:
                last = _get("avg_price", position, 0.0)
            return abs(float(last) * qty) * 0.01
        except Exception:
            pass

    # Fallback to notional magnitude (qty * last_price)
    last = _get("last_price", position, None)
    try:
        if last is None:
            last = _get("avg_price", position, 0.0)
        return abs(float(last) * qty) * 0.01
    except Exception:
        return 0.0


def sort_positions_by_var_desc(
    positions: Iterable[Any],
    md: Any | None = None,
    tf: str = "5m",
    n: int = 14,
    *,
    use_stop_first: bool = True,
) -> List[Any]:
    return sorted(
        list(positions),
        key=lambda p: estimate_var_usd(p, md, tf, n, use_stop_first=use_stop_first),
        reverse=True,
    )
