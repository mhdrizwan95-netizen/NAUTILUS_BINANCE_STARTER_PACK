"""Reusable primitives for strategy-specific screener modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import (
    Any,
    Dict,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
)

from shared.signal_math import confidence_from_score

MappingLike = Mapping[str, Any]


def freeze_mapping(payload: Optional[MappingLike]) -> MappingLike:
    """Return an immutable mapping copy of *payload*."""

    return MappingProxyType(dict(payload or {}))


@dataclass(frozen=True)
class StrategySignal:
    """Normalized execution guidance produced by a screener heuristic."""

    strategy_id: str
    symbol: str
    side: str
    confidence: float
    entry_mode: str
    suggested_stop: Optional[float]
    suggested_tp: Optional[float]
    validity_ttl: int
    metadata: MappingLike = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass mutation guard
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "confidence": round(self.confidence, 6),
            "entry_mode": self.entry_mode,
            "suggested_stop": self.suggested_stop,
            "suggested_tp": self.suggested_tp,
            "validity_ttl": self.validity_ttl,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class StrategyCandidate:
    """Aggregate response returned by a screener for a strategy."""

    score: float
    signal: StrategySignal
    context: MappingLike

    def __post_init__(self) -> None:  # pragma: no cover - dataclass mutation guard
        object.__setattr__(self, "context", freeze_mapping(self.context))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 6),
            "signal": self.signal.as_dict(),
            "context": dict(self.context),
        }


class StrategyScreener:
    """Base implementation for strategy-specific screeners."""

    #: Registry key used by the screener service and HTTP API.
    strategy_key: str = ""
    #: Identifier used inside :class:`StrategySignal` payloads.
    strategy_id: str = ""

    def evaluate(
        self,
        symbol: str,
        meta: Optional[MappingLike],
        klines: Sequence[Sequence[Any]],
        book: Mapping[str, Any],
        features: MappingLike,
    ) -> Optional[StrategyCandidate]:
        raise NotImplementedError


def sma(values: Sequence[float], length: int) -> Optional[float]:
    if length <= 0 or len(values) < length:
        return None
    return sum(values[-length:]) / float(length)


def rsi(values: Sequence[float], length: int = 14) -> Optional[float]:
    if length <= 0:
        return None
    closes = [float(v) for v in values]
    if len(closes) <= length:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, curr in zip(closes, closes[1:]):
        delta = curr - prev
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)
    if len(gains) < length:
        return None
    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length

    def _compute(avg_g: float, avg_l: float) -> float:
        if avg_l == 0.0:
            if avg_g == 0.0:
                return 50.0
            return 100.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    rsi_value = _compute(avg_gain, avg_loss)
    for gain, loss in zip(gains[length:], losses[length:]):
        avg_gain = ((avg_gain * (length - 1)) + gain) / length
        avg_loss = ((avg_loss * (length - 1)) + loss) / length
        rsi_value = _compute(avg_gain, avg_loss)
    return rsi_value


def atr(klines: Sequence[Sequence[Any]], length: int = 14) -> Optional[float]:
    if length <= 0 or len(klines) <= length:
        return None
    prev_close = float(klines[-length - 1][4])
    ranges: list[float] = []
    for row in klines[-length:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        ranges.append(tr)
        prev_close = close
    if not ranges:
        return None
    return sum(ranges) / len(ranges)


def swing_low(klines: Sequence[Sequence[Any]], lookback: int = 8) -> Optional[float]:
    if lookback <= 0 or len(klines) < lookback:
        return None
    lows = [float(row[3]) for row in klines[-lookback:]]
    return min(lows) if lows else None


def swing_high(klines: Sequence[Sequence[Any]], lookback: int = 8) -> Optional[float]:
    if lookback <= 0 or len(klines) < lookback:
        return None
    highs = [float(row[2]) for row in klines[-lookback:]]
    return max(highs) if highs else None


def listing_age(meta: Optional[MappingLike]) -> Optional[float]:
    if not meta:
        return None
    if "listing_age_days" in meta:
        try:
            return max(0.0, float(meta["listing_age_days"]))
        except (TypeError, ValueError):
            return None
    onboard = meta.get("onboard_ts") or meta.get("onboard_time_ms")
    if onboard is None:
        return None
    try:
        ts = float(meta.get("ts", 0.0))
        return max(0.0, (ts - float(onboard)) / 86_400_000.0)
    except Exception:
        return None


def abs_value(value: float) -> float:
    return value if value >= 0 else -value


def merge_context(*contexts: MappingLike) -> MappingLike:
    merged: MutableMapping[str, Any] = {}
    for ctx in contexts:
        merged.update(dict(ctx))
    return freeze_mapping(merged)


__all__ = [
    "StrategySignal",
    "StrategyCandidate",
    "StrategyScreener",
    "freeze_mapping",
    "sma",
    "rsi",
    "atr",
    "rsi",
    "swing_low",
    "swing_high",
    "confidence_from_score",
    "listing_age",
    "abs_value",
    "merge_context",
]
