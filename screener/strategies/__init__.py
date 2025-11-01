"""Strategy-specific screener registry exposing end-to-end heuristics."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .base import StrategyCandidate, StrategyScreener
from .listing import ListingSniperScreener
from .meme import MemeCoinScreener
from .momentum import MomentumBreakoutScreener
from .scalping import ScalpingScreener
from .trend import TrendFollowingScreener


def _build_default_screeners() -> Iterable[StrategyScreener]:
    return (
        TrendFollowingScreener(),
        ScalpingScreener(),
        MomentumBreakoutScreener(),
        MemeCoinScreener(),
        ListingSniperScreener(),
    )


DEFAULT_SCREENERS: tuple[StrategyScreener, ...] = tuple(_build_default_screeners())


def evaluate_strategies(
    symbol: str,
    meta: Optional[Mapping[str, Any]],
    klines: Sequence[Sequence[Any]],
    book: Mapping[str, Any],
    features: Mapping[str, Any],
    screeners: Iterable[StrategyScreener] = DEFAULT_SCREENERS,
) -> Dict[str, StrategyCandidate]:
    results: Dict[str, StrategyCandidate] = {}
    for screener in screeners:
        try:
            candidate = screener.evaluate(symbol, meta, klines, book, features)
        except Exception:
            continue
        if candidate is not None:
            results[screener.strategy_key] = candidate
    return results


__all__ = [
    "StrategyCandidate",
    "StrategyScreener",
    "DEFAULT_SCREENERS",
    "evaluate_strategies",
    "TrendFollowingScreener",
    "ScalpingScreener",
    "MomentumBreakoutScreener",
    "MemeCoinScreener",
    "ListingSniperScreener",
]
