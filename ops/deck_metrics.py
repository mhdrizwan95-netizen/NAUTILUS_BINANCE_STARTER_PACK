"""
Deck metrics hook: convenience helpers to push live metrics and strategy PnL into the Deck API.

Usage::
    from ops.deck_metrics import push_metrics, push_strategy_pnl, push_fill

    push_metrics(
        equity_usd=...,
        pnl_24h=...,
        drawdown_pct=...,
        tick_p50_ms=...,
        tick_p95_ms=...,
        error_rate_pct=...,
        breaker={"equity": False, "venue": False},
    )
    push_strategy_pnl({"scalp": 12.5, "momentum": -3.0})

Environment::
    DECK_URL  Base URL for the deck API (default http://localhost:8002)
"""
from __future__ import annotations

import os
from typing import Dict

import requests

DECK_URL = os.environ.get("DECK_URL", "http://localhost:8002").rstrip("/")


def _post(path: str, payload: Dict) -> None:
    response = requests.post(f"{DECK_URL}{path}", json=payload, timeout=5)
    response.raise_for_status()


def push_metrics(**kwargs) -> None:
    """Push numeric metrics (equity, pnl, latency, breaker status) to the Deck."""
    _post("/metrics/push", {"metrics": kwargs})


def push_strategy_pnl(pnl_by_strategy: Dict[str, float]) -> None:
    """Push per-strategy PnL to the Deck."""
    _post("/metrics/push", {"pnl_by_strategy": pnl_by_strategy})


def push_fill(fill_event: Dict) -> None:
    """Send a trade/fill event (used by the Deck to derive latency distribution)."""
    _post("/trades", fill_event)
