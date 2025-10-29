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
    DECK_URL  Base URL for the Deck API (default http://hmm_deck:8002 inside docker-compose)
"""
from __future__ import annotations

import os
from typing import Dict

import requests

DECK_URL = os.environ.get("DECK_URL", "http://hmm_deck:8002").rstrip("/")
DECK_TOKEN = os.environ.get("DECK_TOKEN", "")


def _headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if DECK_TOKEN:
        headers["X-Deck-Token"] = DECK_TOKEN
    return headers


def _post(path: str, payload: Dict) -> None:
    response = requests.post(f"{DECK_URL}{path}", json=payload, headers=_headers(), timeout=5)
    response.raise_for_status()


def push_metrics(**kwargs) -> bool:
    """Push numeric metrics (equity, pnl, latency, breaker status, wallet snapshot) to the Deck."""
    _post("/metrics/push", {"metrics": kwargs})
    return True


def push_strategy_pnl(pnl_by_strategy: Dict[str, float]) -> bool:
    """Push per-strategy PnL to the Deck."""
    _post("/metrics/push", {"pnl_by_strategy": pnl_by_strategy})
    return True


def push_fill(fill_event: Dict) -> bool:
    """Send a trade/fill event (used by the Deck to derive latency distribution)."""
    _post("/trades", fill_event)
    return True
