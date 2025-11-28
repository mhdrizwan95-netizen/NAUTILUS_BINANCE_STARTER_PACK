"""Lightweight Prometheus counters shared across ops utilities."""

from __future__ import annotations

import math
from prometheus_client import Counter

# We import Metrics only for type hinting if needed, but to avoid circular imports 
# we might just use duck typing or import inside function if strictly necessary.
# However, telemetry_store imports this? No, it doesn't.
# Let's assume we can import Metrics for type hinting if we want, 
# but for now we'll just define the function.

_COUNTER_ERRORS = (ValueError, RuntimeError, KeyError)

_m19_actions = Counter(
    "m19_actions_total",
    "Total scheduler actions triggered",
    ["action"],
)

_m20_incidents = Counter(
    "m20_incidents_total",
    "Total guardian incidents by type",
    ["type"],
)


def inc_scheduler_action(action: str) -> None:
    """Increment the scheduler action counter for the given action label."""
    try:
        _m19_actions.labels(action=str(action)).inc()
    except _COUNTER_ERRORS:
        # Metrics recording must never break recovery automation.
        pass


def inc_guardian_incident(incident_type: str) -> None:
    """Increment the guardian incident counter."""
    try:
        _m20_incidents.labels(type=str(incident_type)).inc()
    except _COUNTER_ERRORS:
        pass


def calculate_strategy_score(
    realized_pnl: float,
    win_rate: float,
    max_drawdown: float,
    drawdown_threshold: float = 0.15
) -> float:
    """
    Calculate a 'Score' for a strategy to determine its capital worthiness.
    
    Formula: Score = Realized_PnL * Win_Rate / (Max_Drawdown + epsilon)
    
    Penalty Box: If Max_Drawdown > Threshold, Score = 0.
    """
    if max_drawdown > drawdown_threshold:
        return 0.0
    
    # Avoid division by zero
    epsilon = 1e-6
    dd_factor = max_drawdown + epsilon
    
    # We only want to reward positive PnL. 
    # If PnL is negative, the score should be low/zero (or negative? Softmax handles negatives but usually we want positive weights).
    # Let's clamp PnL to 0 for the score, or allow negative scores which Softmax will squash.
    # However, standard Softmax: exp(x) / sum(exp(x)). Negative x becomes small positive.
    # But if we want to explicitly PUNISH, a negative score works.
    # But if we want to "Kill" bad strategies, we might want to be more direct.
    
    # Let's use a simple heuristic:
    # If PnL < 0, Score is small.
    
    raw_score = (realized_pnl * win_rate) / dd_factor
    
    # Logarithmic scaling to compress outliers? 
    # For now, raw score is fine, Softmax will handle distribution.
    
    return raw_score


__all__ = ["inc_scheduler_action", "inc_guardian_incident", "calculate_strategy_score"]
