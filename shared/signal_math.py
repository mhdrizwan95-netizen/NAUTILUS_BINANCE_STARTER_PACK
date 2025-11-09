from __future__ import annotations

import math


def confidence_from_score(score: float, *, scale: float = 100.0) -> float:
    """Map an unbounded score to a [0, 1] confidence via logistic.

    - `scale` controls how quickly confidence saturates. Larger values make the
      curve flatter.
    - Input is robust to non-finite values; NaNs are treated as 0.
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 0.0
    if not math.isfinite(s):
        s = 0.0
    k = max(1e-9, float(scale))
    # Standard logistic: 1 / (1 + e^{-x}) with x scaled
    x = s / k
    try:
        y = 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        y = 1.0 if x > 0 else 0.0
    # Clamp to [0, 1] for numerical stability
    if y < 0.0:
        return 0.0
    if y > 1.0:
        return 1.0
    return y


__all__ = ["confidence_from_score"]
