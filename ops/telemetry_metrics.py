"""Lightweight Prometheus counters shared across ops utilities."""

from __future__ import annotations

from prometheus_client import Counter

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


__all__ = ["inc_scheduler_action", "inc_guardian_incident"]
