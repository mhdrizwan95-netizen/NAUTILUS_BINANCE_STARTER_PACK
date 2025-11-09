from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .signal_math import confidence_from_score


@dataclass(frozen=True)
class ListingMetrics:
    score: float
    confidence: float
    stop_price: float | None
    targets: tuple[float, ...]
    context: dict[str, Any]


def generate_listing_targets(
    avg_price: float,
    *,
    stop_pct: float,
    target_multipliers: Iterable[float],
) -> tuple[float | None, list[float]]:
    """Return a protective stop and target prices for a listing entry.

    - `avg_price` is the baseline entry price.
    - `stop_pct` is expressed as a fraction (e.g., 0.10 for 10%).
    - `target_multipliers` are fractional gains (e.g., 0.5 => +50%).
    """
    try:
        px = float(avg_price)
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0:
        return None, []
    try:
        sp = float(stop_pct)
    except (TypeError, ValueError):
        sp = 0.0
    stop = px * max(0.0, 1.0 - sp)
    ladders = []
    for m in target_multipliers:
        try:
            mm = float(m)
        except (TypeError, ValueError):
            continue
        ladders.append(px * (1.0 + max(0.0, mm)))
    return stop, ladders


def compute_listing_metrics(
    *,
    listing_age_days: float,
    volume_multiplier: float,
    move_fraction: float,
    last_price: float | None,
    stop_pct: float,
    target_multipliers: Iterable[float],
) -> ListingMetrics:
    """Compute a simple score and bracket suggestion for listing ideas.

    The scoring favours:
    - younger listings (but still > 0 days)
    - stronger recent price expansion (positive `move_fraction`)
    - higher volume acceleration (`volume_multiplier`)
    """
    try:
        age = max(0.0, float(listing_age_days))
    except (TypeError, ValueError):
        age = 0.0
    try:
        vol = max(0.0, float(volume_multiplier))
    except (TypeError, ValueError):
        vol = 0.0
    try:
        move = float(move_fraction)
    except (TypeError, ValueError):
        move = 0.0

    # Heuristic score: higher on volume/move, modest age decay
    score = max(0.0, (vol - 1.0) * 40.0) + max(0.0, move * 120.0)
    score *= 1.0 / (1.0 + 0.1 * age)
    confidence = confidence_from_score(score, scale=150.0)

    stop = None
    ladders: tuple[float, ...] = ()
    if last_price and last_price > 0:
        stop_val, tgt = generate_listing_targets(
            last_price, stop_pct=stop_pct, target_multipliers=target_multipliers
        )
        stop = stop_val
        ladders = tuple(tgt)

    ctx: dict[str, Any] = {
        "listing_age_days": round(age, 3),
        "volume_multiplier": round(vol, 3),
        "move_fraction": round(move, 6),
        "volume_confirmed": vol >= 1.2,
    }
    if last_price is not None and last_price > 0:
        ctx["last_price"] = float(last_price)

    return ListingMetrics(
        score=score,
        confidence=confidence,
        stop_price=stop,
        targets=ladders,
        context=ctx,
    )


__all__ = [
    "ListingMetrics",
    "generate_listing_targets",
    "compute_listing_metrics",
]
