"""Social sentiment meme coin screener."""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from .base import (
    StrategyCandidate,
    StrategySignal,
    StrategyScreener,
    freeze_mapping,
)
from shared.meme_utils import compute_meme_metrics


class MemeCoinScreener(StrategyScreener):
    """Event-driven screener for meme coin pumps.

    * **Ingest** – join social feeds (Twitter/Reddit/news) with price/volume
      confirmations. Events older than 120 seconds or lacking Binance listings
      are discarded.
    * **Signal** – fire long candidates when social score spikes and 1m volume
      accelerates ≥ 4× baseline with concurrent price expansion (>0.5% in 15m).
    * **Risk/size** – per-trade risk is capped at 0.5–1% of equity; stops start
      wide (8–12%) but tighten immediately. Screener emits laddered targets.
    * **Execute/manage** – execution uses market orders plus hard stops; the
      strategy scales out on predefined rungs and never widens protection. Cool
      downs prevent repeat entries per symbol.
    """

    strategy_key = "meme_coin"
    strategy_id = "meme_coin_sentiment"

    def evaluate(
        self,
        symbol: str,
        meta: Optional[Mapping[str, Any]],
        klines: Sequence[Sequence[Any]],
        book: Mapping[str, Any],
        features: Mapping[str, Any],
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
        last_px = float(features.get("last", 0.0))

        metrics = compute_meme_metrics(
            vol_spike=vol_spike,
            move_fraction=move,
            depth_usd=depth,
            sentiment=float(sentiment) if sentiment is not None else None,
            last_price=last_px if last_px > 0 else None,
            stop_pct=0.09,
            target_multipliers=(1.10, 1.20, 1.35),
        )

        context = freeze_mapping(metrics.context)
        stop = metrics.stop_price
        tp_ladder = list(metrics.targets)
        metadata = freeze_mapping({**dict(context), "take_profit_ladder": tp_ladder})
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side="LONG",
            confidence=metrics.confidence,
            entry_mode="market",
            suggested_stop=stop,
            suggested_tp=tp_ladder[0] if tp_ladder else None,
            validity_ttl=900,
            metadata=metadata,
        )
        return StrategyCandidate(score=metrics.score, signal=signal, context=context)


__all__ = ["MemeCoinScreener"]
