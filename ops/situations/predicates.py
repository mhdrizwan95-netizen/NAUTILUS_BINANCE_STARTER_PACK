from __future__ import annotations

from typing import Any


def _get(feats: dict[str, Any], key: str, default: float | None = None) -> float | None:
    try:
        v = feats.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def pred_ok(pred: dict, feats: dict[str, Any]) -> bool:
    op = pred.get("op")
    feat = pred.get("feat")
    if not feat or not op:
        return False
    if op in (">", "gt"):
        a = _get(feats, feat)
        b = float(pred.get("value", 0))
        return a is not None and a > b
    if op in ("<", "lt"):
        a = _get(feats, feat)
        b = float(pred.get("value", 0))
        return a is not None and a < b
    if op == "between":
        a = _get(feats, feat)
        lo = float(pred.get("low", float("-inf")))
        hi = float(pred.get("high", float("inf")))
        return a is not None and lo <= a <= hi
    if op == "crosses_up":
        a = _get(feats, feat)
        prev = _get(feats, f"{feat}_prev", _get(feats, f"prev_{feat}"))
        b = float(pred.get("value", 0))
        return (prev is not None and a is not None) and prev <= b < a
    if op == "crosses_down":
        a = _get(feats, feat)
        prev = _get(feats, f"{feat}_prev", _get(feats, f"prev_{feat}"))
        b = float(pred.get("value", 0))
        return (prev is not None and a is not None) and prev >= b > a
    if op == "pct_change_gt":
        a = _get(feats, feat)
        prev = _get(feats, f"{feat}_prev", _get(feats, f"prev_{feat}"))
        thr = float(pred.get("value", 0))
        if a is None or prev in (None, 0):
            return False
        return ((a - prev) / abs(prev)) * 100.0 > thr
    return False
