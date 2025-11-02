"""Prometheus and JSON helper utilities shared across ops tooling."""

from __future__ import annotations

import re
from typing import Any


def from_json(obj: dict[str, Any] | None, *keys: str, default: float = 0.0) -> float:
    """Safely extract the first numeric value matching the provided keys."""
    if not isinstance(obj, dict):
        return default
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


prom_line = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{.*?\})?\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)$"
)


def parse_prometheus_text(text: str) -> dict[str, float]:
    """
    Parse Prometheus exposition format into a flat metric mapping.

    Lines with labels are flattened by keeping only the metric name.
    Comments and unparsable lines are ignored.
    """
    metrics: dict[str, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = prom_line.match(line)
        if not match:
            continue
        name, value = match.groups()
        try:
            metrics[name] = float(value)
        except ValueError:
            continue
    return metrics


__all__ = ["from_json", "parse_prometheus_text"]
