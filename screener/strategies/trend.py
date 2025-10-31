"""Trend-following screener adhering to the live trading E2E lifecycle."""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Sequence

from .base import (
    StrategyCandidate,
    StrategySignal,
    StrategyScreener,
    abs_value,
    atr,
    confidence_from_score,
    freeze_mapping,
    listing_age,
    rsi,
    sma,
    swing_low,
)


class TrendFollowingScreener(StrategyScreener):
    """Trend-following screener built around the common E2E lifecycle.

    Triggered on new 1h/4h candle closes, the screener executes the shared
    ``ingest → signal → risk/size → route/execute → protect → manage → exit → log``
    pipeline with the following specialisation:

    * **Ingest & prep** – pull the latest candle batch, refresh EMA/SMA, RSI(14), ATR,
      and confirm that venue + symbol pass global toggles, allow-lists, and volume
      minimums. Young listings (< 3 days) are filtered out to avoid thin regimes.
    * **Signal** – bullish bias requires ``EMA20 > EMA100`` (or SMA 20/50 for the
      cached close array), RSI above 50 and rising, and volume above 1.5× the
      20-bar average. Short ideas are suppressed at the screener stage but the
      strategy module will mirror the logic for futures/margin support.
    * **Risk & size** – position sizing targets ~2% of equity risked using the
      ATR/swing-low distance. Sizing + leverage guards run in the downstream risk
      rails, so the screener only outputs suggested stops/targets alongside a
      confidence score.
    * **Route & execute** – by default entries favour ``limit_pullback`` when
      price is stretched beyond VWAP; otherwise the execution module can route a
      market order with an attached stop and optional take-profit.
    * **Protect & manage** – stops land immediately under the recent swing low or
      ATR×1.8; trailing logic follows EMA20/ATR bands and scale-ins are capped at
      two adds when momentum persists. Monitoring hooks feed into the shared
      position manager.
    * **Exit** – death cross, RSI momentum failure, trailing stop hit, or time
      stop (10–15 bars of stagnation) all terminate the idea.
    * **Post trade** – the downstream engine logs fills, R multiples, and regime
      stats which loop back into analytics.
    """

    strategy_key = "trend_follow"
    strategy_id = "trend_follow"

    def evaluate(
        self,
        symbol: str,
        meta: Optional[Mapping[str, Any]],
        klines: Sequence[Sequence[Any]],
        book: Mapping[str, Any],
        features: Mapping[str, Any],
    ) -> Optional[StrategyCandidate]:
        closes = [float(row[4]) for row in klines if len(row) > 4]
        if len(closes) < 50:
            return None
        volumes = [float(row[5]) for row in klines if len(row) > 5]
        if len(volumes) != len(closes):
            volumes = volumes[-len(closes) :]
        fast = sma(closes, 20)
        slow = sma(closes, 50)
        if not fast or not slow or slow <= 0:
            return None
        if fast <= slow:
            return None
        feature_rsi = features.get("rsi_14") if isinstance(features, Mapping) else None
        if feature_rsi is not None:
            try:
                rsi_val = float(feature_rsi)
            except (TypeError, ValueError):
                rsi_val = None
        else:
            rsi_val = rsi(closes, length=14)
        if rsi_val is None:
            return None
        prev_rsi = None
        if len(closes) - 1 > 14:
            prev_rsi = rsi(closes[:-1], length=14)
        if rsi_val < 52.0:
            return None
        if rsi_val >= 72.0:
            return None
        if prev_rsi is not None and rsi_val <= prev_rsi:
            return None
        if meta:
            age = listing_age(meta)
            if age is not None and age < 3.0:
                return None
            volume_field = (
                meta.get("quote_volume_24h")
                or meta.get("quote_volume")
                or meta.get("notional_24h")
            )
            if volume_field is not None:
                try:
                    if float(volume_field) < 250_000:
                        return None
                except (TypeError, ValueError):
                    pass
        vwap_dev = float(features.get("vwap_dev", 0.0))
        if abs_value(vwap_dev) > 0.15:
            return None
        slope = (fast - slow) / slow
        momentum = float(features.get("r60", 0.0))
        vol_boost = float(features.get("vol_accel_5m_over_30m", 0.0))
        if volumes:
            lookback = min(20, len(volumes))
            recent_avg = sum(volumes[-lookback:]) / float(lookback)
            last_volume = volumes[-1]
            volume_ratio = (last_volume / recent_avg) if recent_avg else 0.0
        else:
            recent_avg = 0.0
            last_volume = 0.0
            volume_ratio = 0.0
        if volume_ratio < 1.2:
            return None
        score = (
            slope * 120.0
            + max(0.0, momentum * 110.0)
            + max(0.0, (rsi_val - 50.0) / 4.0)
            + max(0.0, (volume_ratio - 1.0) * 20.0)
        )
        avg_true_range = atr(klines, length=14) or 0.0
        last_px = closes[-1]
        swing = swing_low(klines, lookback=8) or (
            last_px - avg_true_range * 1.8 if avg_true_range else last_px * 0.98
        )
        stop = round(min(swing, last_px - max(avg_true_range * 1.8, last_px * 0.02)), 6)
        target = round(last_px + max(avg_true_range * 3.0, last_px * 0.03), 6)
        confidence = confidence_from_score(score, scale=150.0)
        ctx_payload: MutableMapping[str, Any] = {
            "fast_sma": round(fast, 6),
            "slow_sma": round(slow, 6),
            "rsi": round(rsi_val, 3),
            "rsi_prev": round(prev_rsi, 3) if prev_rsi is not None else None,
            "volume_ratio": round(volume_ratio, 3),
            "volume_avg": round(recent_avg, 3) if recent_avg else None,
            "last_volume": round(last_volume, 3) if last_volume else None,
            "vol_accel": round(vol_boost, 3),
            "vwap_dev": round(vwap_dev, 4),
            "atr": round(avg_true_range, 6) if avg_true_range else None,
            "slope": round(slope, 6),
        }
        if ctx_payload.get("atr") is None:
            ctx_payload.pop("atr")
        if ctx_payload.get("volume_avg") is None:
            ctx_payload.pop("volume_avg")
        if ctx_payload.get("last_volume") is None:
            ctx_payload.pop("last_volume")
        if volume_ratio >= 1.2 or vol_boost >= 1.5:
            ctx_payload["volume_confirmed"] = True
        context = freeze_mapping(ctx_payload)
        signal = StrategySignal(
            strategy_id=self.strategy_id,
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


__all__ = ["TrendFollowingScreener"]
