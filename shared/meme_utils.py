from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from .signal_math import confidence_from_score


@dataclass(frozen=True)
class MemeMetrics:
    score: float
    confidence: float
    stop_price: Optional[float]
    targets: Tuple[float, ...]
    context: Dict[str, Any]


def generate_meme_bracket(
    avg_price: float,
    *,
    stop_pct: float,
    take_profit_pct: float,
    trail_pct: float,
) -> Tuple[float, float, float]:
    """Return (stop_px, take_profit_px, trail_stop_px) for a long entry.

    All percentages are fractional (e.g., 0.10 => 10%).
    """
    px = float(avg_price)
    sp = max(0.0, float(stop_pct))
    tp = max(0.0, float(take_profit_pct))
    tr = max(0.0, float(trail_pct))
    stop_px = px * (1.0 - sp)
    take_profit_px = px * (1.0 + tp)
    trail_px = px * (1.0 - tr)
    return stop_px, take_profit_px, trail_px


def compute_meme_metrics(
    *,
    vol_spike: float,
    move_fraction: float,
    depth_usd: float,
    sentiment: Optional[float],
    last_price: Optional[float],
    stop_pct: float,
    target_multipliers: Iterable[float],
) -> MemeMetrics:
    """Compute a simple meme signal score and bracket suggestion.

    Scoring favours higher volume spikes, positive momentum, shallower depth
    (to avoid heavy markets), and positive sentiment.
    """
    vs = max(0.0, float(vol_spike))
    mv = float(move_fraction)
    depth = max(0.0, float(depth_usd))
    sent = float(sentiment) if sentiment is not None else 0.0

    # Heuristic score: encourage volume/momentum; penalize very deep books
    score = (max(0.0, vs - 1.0) * 30.0) + (max(0.0, mv) * 110.0)
    if depth > 0:
        score *= 1.0 / (1.0 + min(depth, 2_000_000.0) / 1_000_000.0)
    # Sentiment tilt
    score *= 1.0 + max(min(sent, 1.5), -1.5) * 0.1
    confidence = confidence_from_score(score, scale=150.0)

    stop_px: Optional[float] = None
    targets: Tuple[float, ...] = ()
    if last_price and last_price > 0:
        stop_px = float(last_price) * (1.0 - max(0.0, float(stop_pct)))
        ladders = []
        base = float(last_price)
        for m in target_multipliers:
            try:
                ladders.append(base * (1.0 + max(0.0, float(m))))
            except Exception:
                continue
        targets = tuple(ladders)

    ctx: Dict[str, Any] = {
        "vol_spike": round(vs, 3),
        "move_fraction": round(mv, 6),
        "depth_usd": round(depth, 3),
        "sentiment": round(sent, 3),
    }
    if last_price is not None and last_price > 0:
        ctx["last_price"] = float(last_price)

    return MemeMetrics(
        score=score,
        confidence=confidence,
        stop_price=stop_px,
        targets=targets,
        context=ctx,
    )


__all__ = [
    "MemeMetrics",
    "generate_meme_bracket",
    "compute_meme_metrics",
]

