"""
Dynamic risk, exposure and sizing policy (no hardcoded min/max).
Use these helpers in RiskRails instead of env-driven constants.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Literal, Tuple
import math

Mode = Literal["red", "yellow", "green"]


@dataclass
class MarketSnapshot:
    symbol: str
    mark: float
    atr_pct: float
    spread_bps: float
    book_depth_usd: float
    vol1m_usd: float
    funding_rate_8h: Optional[float] = None
    event_heat: float = 0.0
    velocity: float = 0.0
    liq_score: float = 0.0


@dataclass
class AccountState:
    equity_usd: float
    open_risk_sum_pct: float
    open_positions: int
    exposure_total_usd: float
    exposure_by_symbol_usd: Dict[str, float]


@dataclass
class RegimeSignal:
    p_win_1h: float
    pnl_slope_1h: float
    drawdown_pct_7d: float
    breadth_up_pct: float
    volatility_state: Literal["low", "med", "high"]


@dataclass
class StrategyContext:
    name: str
    type: Literal["scalp", "momentum", "trend", "event"]
    base_timeframe: Literal["1m", "5m", "15m", "1h", "4h"]
    leverage_allowed: bool
    priority: int


def choose_mode(regime: RegimeSignal) -> Mode:
    score = 0.0
    score += 1.0 * (regime.p_win_1h - 0.5) * 2.0
    score += 0.8 * math.tanh(regime.pnl_slope_1h)
    score += 0.5 * (regime.breadth_up_pct - 0.5) * 2.0
    if regime.volatility_state == "high":
        score += 0.15
    elif regime.volatility_state == "low":
        score -= 0.10
    score -= 0.8 * max(0.0, regime.drawdown_pct_7d - 0.10)
    if score >= 0.65:
        return "green"
    if score <= -0.35:
        return "red"
    return "yellow"


def per_trade_risk_pct(mode: Mode, strat: StrategyContext) -> float:
    base = {
        ("scalp", "red"): 0.004,
        ("scalp", "yellow"): 0.008,
        ("scalp", "green"): 0.012,
        ("momentum", "red"): 0.006,
        ("momentum", "yellow"): 0.012,
        ("momentum", "green"): 0.018,
        ("trend", "red"): 0.007,
        ("trend", "yellow"): 0.015,
        ("trend", "green"): 0.022,
        ("event", "red"): 0.003,
        ("event", "yellow"): 0.007,
        ("event", "green"): 0.012,
    }[(strat.type, mode)]
    tf_adj = {"1m": -0.0015, "5m": -0.001, "15m": 0.0, "1h": 0.001, "4h": 0.002}[
        strat.base_timeframe
    ]
    return max(0.0005, base + tf_adj)


def target_stop_pct(strat: StrategyContext, mkt: MarketSnapshot) -> float:
    k_base = {"scalp": 0.9, "momentum": 1.2, "trend": 1.6, "event": 1.3}[strat.type]
    spread_penalty = min(0.5, mkt.spread_bps / 10_000.0 * 5.0)
    liq_bonus = 0.2 * mkt.liq_score
    heat_bonus = -0.2 * mkt.event_heat if strat.type in ("momentum", "event") else 0.0
    k = max(0.6, k_base + spread_penalty - liq_bonus + heat_bonus)
    return max(0.002, k * max(0.001, mkt.atr_pct))


def dynamic_position_notional_usd(
    mode: Mode, strat: StrategyContext, mkt: MarketSnapshot, acct: AccountState
) -> Tuple[float, float]:
    stop_pct = target_stop_pct(strat, mkt)
    risk_pct = per_trade_risk_pct(mode, strat)
    free_risk = max(
        0.0,
        (0.10 if mode == "green" else 0.06 if mode == "yellow" else 0.03) - acct.open_risk_sum_pct,
    )
    risk_use = min(risk_pct, free_risk if free_risk > 0 else risk_pct * 0.5)
    risk_usd = acct.equity_usd * risk_use
    size_by_risk = risk_usd / max(1e-6, stop_pct)
    impact_cap = 0.02 if mode == "green" else (0.015 if mode == "yellow" else 0.01)
    size_by_liquidity = impact_cap * mkt.vol1m_usd
    quality = max(0.05, min(1.0, 1.0 - (mkt.spread_bps / 50.0))) * (0.5 + 0.5 * mkt.liq_score)
    size_quality_adj = size_by_risk * quality
    size_usd = min(size_quality_adj, size_by_liquidity)
    return (max(0.0, size_usd), stop_pct)


def dynamic_concurrent_limits(mode: Mode, acct: AccountState) -> Tuple[int, float]:
    base_positions = {"red": 3, "yellow": 6, "green": 10}[mode]
    base_risk_cap = {"red": 0.03, "yellow": 0.06, "green": 0.09}[mode]
    import math as _m

    scale = 1.0 + min(0.5, _m.log10(max(1.0, acct.equity_usd / 2000.0)) * 0.25)
    positions = int(max(1, base_positions * scale))
    residual_cap = max(0.01, base_risk_cap - 0.004 * max(0, acct.open_positions - positions))
    return (positions, residual_cap)


def dynamic_drawdown_limits(mode: Mode, regime: RegimeSignal) -> Tuple[float, float]:
    base_daily = {"red": 0.035, "yellow": 0.055, "green": 0.075}[mode]
    base_peak = {"red": 0.12, "yellow": 0.18, "green": 0.24}[mode]
    stress = max(0.0, regime.drawdown_pct_7d - 0.08)
    pvar = abs(regime.p_win_1h - 0.5)
    daily = max(0.02, base_daily - 0.015 * stress + 0.01 * pvar)
    peak = max(0.10, base_peak - 0.10 * stress + 0.05 * pvar)
    return (daily, peak)
