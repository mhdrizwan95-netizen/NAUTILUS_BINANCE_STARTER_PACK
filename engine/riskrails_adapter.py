"""
RiskRails adapter: convenience helpers to thread dynamic_policy into existing sizing logic.

Call `compute_order(...)` from your risk checks to obtain mode, dynamic position sizing,
and updated exposure caps based on live market/account inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from engine.dynamic_policy import (
    AccountState,
    MarketSnapshot,
    StrategyContext,
    choose_mode,
    dynamic_concurrent_limits,
    dynamic_drawdown_limits,
    dynamic_position_notional_usd,
)


@dataclass
class LiveFeatures:
    symbol: str
    price: float
    atr_pct: float
    spread_bps: float
    depth10bps_usd: float
    vol1m_usd: float
    funding_rate_8h: float
    event_heat: float
    velocity: float
    liq_score: float


def compute_order(
    *,
    strat_name: str,
    strat_type: str,
    base_tf: str,
    leverage_allowed: bool,
    live: LiveFeatures,
    equity_usd: float,
    open_risk_sum_pct: float,
    open_positions: int,
    exposure_total_usd: float,
    exposure_by_symbol: Dict[str, float],
    regime_signal,
) -> Dict[str, float]:
    """Return a dict containing dynamic sizing, stops, and concurrency caps."""
    strat = StrategyContext(
        name=strat_name,
        type=strat_type,
        base_timeframe=base_tf,
        leverage_allowed=leverage_allowed,
        priority=5,
    )
    mkt = MarketSnapshot(
        symbol=live.symbol,
        mark=live.price,
        atr_pct=live.atr_pct,
        spread_bps=live.spread_bps,
        book_depth_usd=live.depth10bps_usd,
        vol1m_usd=live.vol1m_usd,
        funding_rate_8h=live.funding_rate_8h,
        event_heat=live.event_heat,
        velocity=live.velocity,
        liq_score=live.liq_score,
    )
    acct = AccountState(
        equity_usd=equity_usd,
        open_risk_sum_pct=open_risk_sum_pct,
        open_positions=open_positions,
        exposure_total_usd=exposure_total_usd,
        exposure_by_symbol_usd=exposure_by_symbol,
    )

    mode = choose_mode(regime_signal)
    size_usd, stop_pct = dynamic_position_notional_usd(mode, strat, mkt, acct)
    max_positions, risk_cap = dynamic_concurrent_limits(mode, acct)
    daily_stop, peak_stop = dynamic_drawdown_limits(mode, regime_signal)

    return {
        "mode": mode,
        "size_usd": size_usd,
        "stop_pct": stop_pct,
        "max_positions": max_positions,
        "risk_cap_sumR": risk_cap,
        "daily_stop_pct": daily_stop,
        "peak_drawdown_stop_pct": peak_stop,
    }
