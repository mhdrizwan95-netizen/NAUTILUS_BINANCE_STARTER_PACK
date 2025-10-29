"""High frequency scalping screener built for the shared pipeline."""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Sequence

from .base import (
    StrategyCandidate,
    StrategySignal,
    StrategyScreener,
    abs_value,
    confidence_from_score,
    freeze_mapping,
)


class ScalpingScreener(StrategyScreener):
    """Scalping screener mirroring the range/mean-revert + micro-momentum flow.

    * **Ingest** – subscribe to aggTrades/order book snapshots and build
      micro-bars, spread, depth, imbalance, RSI(2), and micro-ATR metrics on a
      rolling basis. The screener is invoked by the parent module whenever a new
      1m aggregation closes or order-book deltas cross thresholds.
    * **Signal** – identify range bounces (RSI(2)<10 at support/VWAP bands) or
      micro momentum nudges (first thrust with positive imbalance). Spreads must
      exceed the taker fee edge and volatility spikes pause the module.
    * **Risk/size** – downstream risk rails clamp per-trade risk to 0.05–0.2% of
      equity with symmetric SL/TP ~0.1–0.3%; screener returns bracket guidance
      and confidence.
    * **Route/execute** – entries prefer post-only limit orders. If they do not
      fill within the TTL window, execution will cancel the idea.
    * **Protect/manage** – hard stops (market) are armed immediately, optional
      breakeven shifts after partial fills, and a time-stop expires the trade.
    * **Exit/log** – TP, SL, TTL, or an order-book flip closes the position and
      metrics capture maker/taker mix and streaks.
    """

    strategy_key = "scalping"
    strategy_id = "scalping"

    def evaluate(
        self,
        symbol: str,
        meta: Optional[Mapping[str, Any]],
        klines: Sequence[Sequence[Any]],
        book: Mapping[str, Any],
        features: Mapping[str, Any],
    ) -> Optional[StrategyCandidate]:
        spread_ratio = float(features.get("spread_over_atr", 9.0) or 9.0)
        if spread_ratio > 1.25:
            return None
        vwap_dev = float(features.get("vwap_dev", 0.0))
        if abs_value(vwap_dev) > 0.004:
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
            (0.004 - abs_value(vwap_dev)) * 2_500.0
            + (1.5 - min(spread_ratio, 1.5)) * 60.0
            + min(depth_usd / 500_000.0, 1.0) * 30.0
            - abs_value(float(features.get("r15", 0.0))) * 60.0
        )
        ctx_payload: MutableMapping[str, Any] = {
            "spread_over_atr": round(spread_ratio, 4),
            "vwap_dev": round(vwap_dev, 5),
            "depth_usd": round(depth_usd, 2),
        }
        if imbalance:
            ctx_payload["orderbook_imbalance"] = round(imbalance, 6)
        context = freeze_mapping(ctx_payload)
        last_px = float(features.get("last", 0.0))
        stop = round(last_px * (1.0 - 0.0015), 6) if last_px else None
        target = round(last_px * (1.0 + 0.0015), 6) if last_px else None
        confidence = confidence_from_score(score, scale=400.0)
        signal = StrategySignal(
            strategy_id=self.strategy_id,
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


__all__ = ["ScalpingScreener"]
