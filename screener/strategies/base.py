"""Reusable primitives for strategy-specific screener modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence


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


def rsi(values: Sequence[float], length: int = 14) -> Optional[float]:
    if length <= 1 or len(values) <= length:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)
    avg_gain = sum(gains[:length]) / float(length)
    avg_loss = sum(losses[:length]) / float(length)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss if avg_loss else float("inf")
    rsi_val = 100.0 - (100.0 / (1.0 + rs))
    if len(gains) == length:
        return rsi_val
    for i in range(length, len(gains)):
        avg_gain = ((avg_gain * (length - 1)) + gains[i]) / float(length)
        avg_loss = ((avg_loss * (length - 1)) + losses[i]) / float(length)
        if avg_loss == 0:
            rsi_val = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100.0 - (100.0 / (1.0 + rs))
    return rsi_val


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


def confidence_from_score(raw: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    normalized = raw / scale
    return max(0.0, min(1.0, normalized))


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
    "atr",
    "rsi",
    "swing_low",
    "swing_high",
    "confidence_from_score",
    "listing_age",
    "abs_value",
    "merge_context",
]
