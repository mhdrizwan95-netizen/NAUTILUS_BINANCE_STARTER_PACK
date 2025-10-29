"""Token listing sniper screener."""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Sequence

from .base import (
    StrategyCandidate,
    StrategySignal,
    StrategyScreener,
    confidence_from_score,
    freeze_mapping,
    listing_age,
)


class ListingSniperScreener(StrategyScreener):
    """Screener for new Binance token listings following the lifecycle.

    * **Ingest** – monitor Binance listing announcements, refresh exchange info
      for filters, and fetch rapid 1m bars once trading opens.
    * **Signal** – focus on listings younger than 14 days with strong volume
      acceleration and positive price delta. External venues already +200% are
      filtered by upstream guards.
    * **Risk/size** – ideas risk 0.5–1% equity with tiny notionals ($25–$100),
      stops around −10%, and laddered TPs (+50/+100% etc.).
    * **Execute/manage** – initial impulse or wait–retest–break entry modes are
      handled downstream; stops/targets are attached immediately with tight
      trailing once the first rung hits.
    """

    strategy_key = "listing_sniper"
    strategy_id = "listing_sniper"

    def evaluate(
        self,
        symbol: str,
        meta: Optional[Mapping[str, Any]],
        klines: Sequence[Sequence[Any]],
        book: Mapping[str, Any],
        features: Mapping[str, Any],
    ) -> Optional[StrategyCandidate]:
        age = listing_age(meta)
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
        context = freeze_mapping(ctx_payload)
        last_px = float(features.get("last", 0.0))
        stop = round(last_px * 0.9, 6) if last_px else None
        tp = round(last_px * 1.25, 6) if last_px else None
        confidence = confidence_from_score(score, scale=600.0)
        signal = StrategySignal(
            strategy_id=self.strategy_id,
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


__all__ = ["ListingSniperScreener"]
