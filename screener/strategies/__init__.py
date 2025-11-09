"""Strategy-specific screener registry exposing end-to-end heuristics."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .base import StrategyCandidate, StrategyScreener
from .listing import ListingSniperScreener
from .meme import MemeCoinScreener
from .momentum import MomentumBreakoutScreener
from .scalping import ScalpingScreener
from .trend import TrendFollowingScreener

logger = logging.getLogger("screener.strategies")
_SCREEN_ERRORS = (ValueError, RuntimeError, TypeError)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


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
    meta: Mapping[str, Any] | None,
    klines: Sequence[Sequence[Any]],
    book: Mapping[str, Any],
    features: Mapping[str, Any],
    screeners: Iterable[StrategyScreener] = DEFAULT_SCREENERS,
) -> dict[str, StrategyCandidate]:
    results: dict[str, StrategyCandidate] = {}
    for screener in screeners:
        try:
            candidate = screener.evaluate(symbol, meta, klines, book, features)
        except _SCREEN_ERRORS as exc:
            _log_suppressed(f"screener.{getattr(screener, 'strategy_key', 'unknown')}", exc)
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
