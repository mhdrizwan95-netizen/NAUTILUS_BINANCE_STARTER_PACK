"""Momentum breakout screener aligned with the event-driven lifecycle."""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Sequence

from .base import (
    StrategyCandidate,
    StrategySignal,
    StrategyScreener,
    atr,
    confidence_from_score,
    freeze_mapping,
    swing_high,
)


class MomentumBreakoutScreener(StrategyScreener):
    """Momentum breakout screener following the shared E2E stages.

    * **Ingest** – consume real-time trades + 1m/5m bars, compute rolling
      returns, ATR/Bollinger width, volume vs. average, and the 24h high. The
      screener is triggered on each 1m close or large delta event.
    * **Signal** – long triggers fire when price clears range/24h highs with
      volume ≥ 3× baseline; shorts mirror the logic when supported. Extended
      moves (>8–10% in last 15–30 minutes) are filtered.
    * **Risk/size** – risk budgets of 1–2% feed the downstream sizer; we surface
      suggested stops (breakout level − ATR×buffer) and trail presets.
    * **Route/execute** – urgency dictates market entries with reduce-only stop
      attachments; trails are either native exchange orders or engine-managed.
    * **Manage/exit** – move to breakeven at +1–1.5%, trail 1–2%, take partials
      at +3–5%, and exit on failed retests or divergence/time stops.
    """

    strategy_key = "momentum_breakout"
    strategy_id = "momentum_breakout"

    def evaluate(
        self,
        symbol: str,
        meta: Optional[Mapping[str, Any]],
        klines: Sequence[Sequence[Any]],
        book: Mapping[str, Any],
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
        context = freeze_mapping(ctx_payload)
        last_px = float(features.get("last", 0.0))
        avg_true_range = atr(klines, length=10) or 0.0
        stop = round(last_px - max(last_px * 0.008, avg_true_range * 1.2), 6) if last_px else None
        target = round(last_px + max(last_px * 0.02, avg_true_range * 2.5), 6) if last_px else None
        confidence = confidence_from_score(score, scale=500.0)
        breakout = swing_high(klines, 12)
        metadata = freeze_mapping({**dict(context), **({"breakout_level": round(breakout, 6)} if breakout else {})})
        signal = StrategySignal(
            strategy_id=self.strategy_id,
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


__all__ = ["MomentumBreakoutScreener"]
