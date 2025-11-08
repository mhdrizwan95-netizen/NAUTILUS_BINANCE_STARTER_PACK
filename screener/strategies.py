"""Strategy-specific symbol heuristics for the screener service."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence


def _freeze_mapping(payload: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Return an immutable mapping representation."""

    return MappingProxyType(dict(payload or {}))


@dataclass(frozen=True)
class StrategySignal:
    """Execution-oriented metadata produced by a strategy heuristic."""

    strategy_id: str
    symbol: str
    side: str
    confidence: float
    entry_mode: str
    suggested_stop: Optional[float]
    suggested_tp: Optional[float]
    validity_ttl: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True)
class StrategyCandidate:
    """Normalized representation returned by each strategy heuristic."""

    score: float
    signal: StrategySignal
    context: Mapping[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 6),
            "signal": self.signal.as_dict(),
            "context": dict(self.context),
        }

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", _freeze_mapping(self.context))


def _sma(values: Sequence[float], length: int) -> Optional[float]:
    if length <= 0 or len(values) < length:
        return None
    return sum(values[-length:]) / float(length)


def _abs(value: float) -> float:
    return value if value >= 0 else -value


def _atr(klines: Sequence[Sequence[Any]], length: int = 14) -> Optional[float]:
    if length <= 0 or len(klines) <= length:
        return None
    prev_close = float(klines[-length - 1][4])
    trs: List[float] = []
    for row in klines[-length:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if not trs:
        return None
    return sum(trs) / len(trs)


def _swing_low(klines: Sequence[Sequence[Any]], lookback: int = 8) -> Optional[float]:
    if lookback <= 0 or len(klines) < lookback:
        return None
    lows = [float(row[3]) for row in klines[-lookback:]]
    return min(lows) if lows else None


def _swing_high(klines: Sequence[Sequence[Any]], lookback: int = 8) -> Optional[float]:
    if lookback <= 0 or len(klines) < lookback:
        return None
    highs = [float(row[2]) for row in klines[-lookback:]]
    return max(highs) if highs else None


def _confidence_from_score(raw: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    normalized = raw / scale
    return max(0.0, min(1.0, normalized))


def _listing_age(meta: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not meta:
        return None
    age = meta.get("listing_age_days")
    if age is None:
        onboard = meta.get("onboard_ts") or meta.get("onboard_time_ms")
        if onboard is not None:
            try:
                return max(0.0, (meta.get("ts", 0.0) - float(onboard)) / 86_400_000.0)
            except Exception:
                return None
        return None
    try:
        return float(age)
    except (TypeError, ValueError):
        return None


def trend_follow_candidate(
    symbol: str,
    klines: List[List[Any]],
    closes: Sequence[float],
    features: Mapping[str, Any],
    meta: Optional[Mapping[str, Any]] = None,
) -> Optional[StrategyCandidate]:
    if len(closes) < 50:
        return None
    fast = _sma(closes, 20)
    slow = _sma(closes, 50)
    if not fast or not slow or slow <= 0:
        return None
    if fast <= slow:
        return None
    rsi = features.get("rsi_14")
    if rsi is None:
        return None
    try:
        rsi_val = float(rsi)
    except (TypeError, ValueError):
        return None
    if rsi_val < 52.0:
        return None
    volume_check = None
    if meta:
        age = _listing_age(meta)
        if age is not None and age < 3.0:
            return None
        volume_check = (
            meta.get("quote_volume_24h") or meta.get("quote_volume") or meta.get("notional_24h")
        )
    if volume_check is not None:
        try:
            if float(volume_check) < 250_000:
                return None
        except (TypeError, ValueError):
            pass
    slope = (fast - slow) / slow
    momentum = float(features.get("r60", 0.0))
    vol_boost = float(features.get("vol_accel_5m_over_30m", 0.0))
    vwap_dev = float(features.get("vwap_dev", 0.0))
    if _abs(vwap_dev) > 0.15:
        return None
    score = slope * 120.0 + max(0.0, momentum * 110.0) + max(0.0, (rsi_val - 50.0) / 4.0)
    atr = _atr(klines, length=14) or 0.0
    last_px = closes[-1]
    swing = _swing_low(klines, lookback=8) or (last_px - atr * 1.8 if atr else last_px * 0.98)
    stop = round(min(swing, last_px - max(atr * 1.8, last_px * 0.02)), 6)
    target = round(last_px + max(atr * 3.0, last_px * 0.03), 6)
    confidence = _confidence_from_score(score, scale=150.0)
    ctx_payload: MutableMapping[str, Any] = {
        "fast_sma": round(fast, 6),
        "slow_sma": round(slow, 6),
        "rsi": round(rsi_val, 3),
        "vol_accel": round(vol_boost, 3),
        "vwap_dev": round(vwap_dev, 4),
        "atr": round(atr, 6) if atr else None,
        "slope": round(slope, 6),
    }
    if ctx_payload.get("atr") is None:
        ctx_payload.pop("atr")
    if vol_boost >= 1.5:
        ctx_payload["volume_confirmed"] = True
    context = _freeze_mapping(ctx_payload)
    signal = StrategySignal(
        strategy_id="trend_follow",
        symbol=symbol,
        side="LONG",
        confidence=confidence,
        entry_mode="limit_pullback" if vwap_dev > 0.01 else "market",
        suggested_stop=stop,
        suggested_tp=target,
        validity_ttl=4 * 60 * 60,
        metadata=context,
    )
    return StrategyCandidate(score=score, signal=signal, context=context)


def scalping_candidate(
    symbol: str,
    features: Mapping[str, Any],
    book: Mapping[str, Any],
) -> Optional[StrategyCandidate]:
    spread_ratio = float(features.get("spread_over_atr", 9.0) or 9.0)
    if spread_ratio > 1.25:
        return None
    vwap_dev = float(features.get("vwap_dev", 0.0))
    if _abs(vwap_dev) > 0.004:
        return None
    depth_usd = float(features.get("depth_usd", 0.0))
    if depth_usd < 100_000:
        return None
    imbalance = 0.0
    try:
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        best_bid = float(bids[0][0]) if bids else 0.0
        best_ask = float(asks[0][0]) if asks else 0.0
        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2.0
            imbalance = (best_bid - mid) / mid
    except Exception:
        imbalance = 0.0
    score = (
        (0.004 - _abs(vwap_dev)) * 2_500.0
        + (1.5 - min(spread_ratio, 1.5)) * 60.0
        + min(depth_usd / 500_000.0, 1.0) * 30.0
        - _abs(float(features.get("r15", 0.0))) * 60.0
    )
    ctx_payload: MutableMapping[str, Any] = {
        "spread_over_atr": round(spread_ratio, 4),
        "vwap_dev": round(vwap_dev, 5),
        "depth_usd": round(depth_usd, 2),
    }
    if imbalance:
        ctx_payload["orderbook_imbalance"] = round(imbalance, 6)
    context = _freeze_mapping(ctx_payload)
    last_px = float(features.get("last", 0.0))
    stop = round(last_px * (1.0 - 0.0015), 6) if last_px else None
    target = round(last_px * (1.0 + 0.0015), 6) if last_px else None
    confidence = _confidence_from_score(score, scale=400.0)
    signal = StrategySignal(
        strategy_id="scalping",
        symbol=symbol,
        side="LONG" if vwap_dev <= 0 else "SHORT",
        confidence=confidence,
        entry_mode="post_only_limit",
        suggested_stop=stop,
        suggested_tp=target,
        validity_ttl=120,
        metadata=context,
    )
    return StrategyCandidate(score=score, signal=signal, context=context)


def momentum_candidate(
    symbol: str,
    klines: List[List[Any]],
    features: Mapping[str, Any],
) -> Optional[StrategyCandidate]:
    move_15 = float(features.get("r15", 0.0))
    long_term = float(features.get("r60", 0.0))
    vol_boost = float(features.get("vol_accel_5m_over_30m", 0.0))
    depth = float(features.get("depth_usd", 0.0))
    if move_15 <= 0.01:
        return None
    if vol_boost < 1.4:
        return None
    if depth < 200_000.0:
        return None
    score = move_15 * 420.0 + max(0.0, long_term * 220.0) + max(0.0, vol_boost - 1.0) * 30.0
    ctx_payload: MutableMapping[str, Any] = {
        "r15_pct": round(move_15 * 100.0, 3),
        "r60_pct": round(long_term * 100.0, 3),
        "vol_multiplier": round(vol_boost, 3),
        "depth_usd": round(depth, 2),
    }
    context = _freeze_mapping(ctx_payload)
    last_px = float(features.get("last", 0.0))
    atr = _atr(klines, length=10) or 0.0
    stop = round(last_px - max(last_px * 0.008, atr * 1.2), 6) if last_px else None
    target = round(last_px + max(last_px * 0.02, atr * 2.5), 6) if last_px else None
    confidence = _confidence_from_score(score, scale=500.0)
    breakout = _swing_high(klines, 12)
    extra_meta = {}
    if breakout is not None:
        extra_meta["breakout_level"] = round(breakout, 6)
    metadata = _freeze_mapping({**dict(context), **extra_meta})
    signal = StrategySignal(
        strategy_id="momentum_breakout",
        symbol=symbol,
        side="LONG",
        confidence=confidence,
        entry_mode="market",
        suggested_stop=stop,
        suggested_tp=target,
        validity_ttl=600,
        metadata=metadata,
    )
    return StrategyCandidate(score=score, signal=signal, context=context)


def meme_candidate(
    symbol: str,
    features: Mapping[str, Any],
    meta: Optional[Mapping[str, Any]] = None,
) -> Optional[StrategyCandidate]:
    vol_spike = float(features.get("vol_accel_1m_over_30m", 0.0))
    if vol_spike < 4.0:
        return None
    move = float(features.get("r15", 0.0))
    if move <= 0.005:
        return None
    depth = float(features.get("depth_usd", 0.0))
    if depth > 1_500_000.0:
        return None
    sentiment = None
    if meta:
        sentiment = meta.get("news_score") or meta.get("social_score")
    score = vol_spike * 12.0 + move * 1_200.0
    if sentiment is not None:
        try:
            score += float(sentiment)
        except (TypeError, ValueError):
            pass
    ctx_payload: MutableMapping[str, Any] = {
        "vol_spike": round(vol_spike, 3),
        "move_pct": round(move * 100.0, 3),
        "depth_usd": round(depth, 2),
    }
    if sentiment is not None:
        ctx_payload["sentiment"] = round(float(sentiment), 3)
    context = _freeze_mapping(ctx_payload)
    last_px = float(features.get("last", 0.0))
    stop = round(last_px * (1.0 - 0.09), 6) if last_px else None
    tp_ladder = [round(last_px * mult, 6) for mult in (1.1, 1.2, 1.35)] if last_px else []
    confidence = _confidence_from_score(score, scale=1500.0)
    metadata = _freeze_mapping({**dict(context), "take_profit_ladder": tp_ladder})
    signal = StrategySignal(
        strategy_id="meme_coin_sentiment",
        symbol=symbol,
        side="LONG",
        confidence=confidence,
        entry_mode="market",
        suggested_stop=stop,
        suggested_tp=tp_ladder[0] if tp_ladder else None,
        validity_ttl=900,
        metadata=metadata,
    )
    return StrategyCandidate(score=score, signal=signal, context=context)


def listing_candidate(
    symbol: str,
    features: Mapping[str, Any],
    meta: Optional[Mapping[str, Any]] = None,
) -> Optional[StrategyCandidate]:
    age = _listing_age(meta)
    if age is None or age > 14.0:
        return None
    vol_boost = float(features.get("vol_accel_5m_over_30m", 0.0))
    move = float(features.get("r60", 0.0))
    score = max(0.0, 14.0 - age) * 6.0 + max(0.0, vol_boost - 1.0) * 24.0 + max(0.0, move) * 520.0
    ctx_payload: MutableMapping[str, Any] = {
        "listing_age_days": round(age, 3),
        "vol_multiplier": round(vol_boost, 3),
        "move_pct": round(move * 100.0, 3),
    }
    context = _freeze_mapping(ctx_payload)
    last_px = float(features.get("last", 0.0))
    stop = round(last_px * 0.9, 6) if last_px else None
    tp = round(last_px * 1.25, 6) if last_px else None
    confidence = _confidence_from_score(score, scale=600.0)
    signal = StrategySignal(
        strategy_id="listing_sniper",
        symbol=symbol,
        side="LONG",
        confidence=confidence,
        entry_mode="market",
        suggested_stop=stop,
        suggested_tp=tp,
        validity_ttl=1_800,
        metadata=context,
    )
    return StrategyCandidate(score=score, signal=signal, context=context)


def evaluate_strategies(
    symbol: str,
    meta: Optional[Mapping[str, Any]],
    klines: List[List[Any]],
    book: Mapping[str, Any],
    features: Mapping[str, Any],
) -> Dict[str, StrategyCandidate]:
    closes: List[float] = [float(row[4]) for row in klines if len(row) > 4]
    results: Dict[str, StrategyCandidate] = {}
    trend = trend_follow_candidate(symbol, klines, closes, features, meta)
    if trend is not None:
        results["trend_follow"] = trend
    scalper = scalping_candidate(symbol, features, book)
    if scalper is not None:
        results["scalping"] = scalper
    momentum = momentum_candidate(symbol, klines, features)
    if momentum is not None:
        results["momentum_breakout"] = momentum
    meme = meme_candidate(symbol, features, meta)
    if meme is not None:
        results["meme_coin"] = meme
    listing = listing_candidate(symbol, features, meta)
    if listing is not None:
        results["listing_sniper"] = listing
    return results


__all__ = [
    "StrategyCandidate",
    "StrategySignal",
    "evaluate_strategies",
    "listing_candidate",
    "meme_candidate",
    "momentum_candidate",
    "scalping_candidate",
    "trend_follow_candidate",
]
