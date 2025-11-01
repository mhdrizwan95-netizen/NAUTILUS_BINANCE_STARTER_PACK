"""
Allocator daemon: adjusts strategy risk_share by recent performance.
- Pulls rolling PnL by strategy from Deck API (/status or pushed via /metrics/push).
- Computes scores (EMA PnL with drawdown penalty) and writes new risk_share via /allocator/weights.
- Thompson/UCB-lite hybrid to keep a bit of exploration.
ENV:
  DECK_URL: base URL of deck API (default http://localhost:8002)
  REFRESH_SEC: loop interval seconds (default 600)
  MAX_SHARE: max per-strategy share (default 0.55)
  MIN_SHARE: min per-strategy share (default 0.05)
  EXPLORATION: 0..1 exploration weight added to each score (default 0.08)
  EMA_ALPHA: 0..1 smoothing of PnL EMA (default 0.35)
"""

from __future__ import annotations

import math
import os
import random
import time
from typing import Dict

import requests

DECK = os.environ.get("DECK_URL", "http://localhost:8002").rstrip("/")
REFRESH = int(os.environ.get("REFRESH_SEC", "600"))
MAX_SHARE = float(os.environ.get("MAX_SHARE", "0.55"))
MIN_SHARE = float(os.environ.get("MIN_SHARE", "0.05"))
EXPLORATION = float(os.environ.get("EXPLORATION", "0.08"))
ALPHA = float(os.environ.get("EMA_ALPHA", "0.35"))

ema_store: Dict[str, float] = {}
var_store: Dict[str, float] = {}


def get_status() -> dict | None:
    try:
        response = requests.get(f"{DECK}/status", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[allocator] status error: {exc}")
    return None


def set_weight(strategy: str, share: float) -> bool:
    try:
        payload = {"strategy": strategy, "risk_share": share}
        response = requests.post(f"{DECK}/allocator/weights", json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[allocator] set_weight error for {strategy}: {exc}")
        return False


def norm_scores(scores: Dict[str, float]) -> Dict[str, float]:
    clipped = {key: max(1e-6, value) for key, value in scores.items()}
    total = sum(clipped.values())
    if total <= 0:
        return {key: 1.0 / len(clipped) for key in clipped} if clipped else {}
    return {key: value / total for key, value in clipped.items()}


def main() -> None:
    print(f"[allocator] starting; deck={DECK} refresh={REFRESH}s max_share={MAX_SHARE}")
    while True:
        status = get_status()
        if not status:
            time.sleep(min(REFRESH, 10))
            continue

        strategies = list((status.get("strategies") or {}).keys())
        if not strategies:
            time.sleep(min(REFRESH, 10))
            continue

        pnl_by_strat = (
            status.get("pnl_by_strategy")
            or (status.get("metrics") or {}).get("pnl_by_strategy")
            or {}
        )
        base_weights = {
            strat: status["strategies"][strat]["risk_share"] for strat in strategies
        }

        equity = (status.get("metrics") or {}).get("equity_usd") or 1.0
        scores: Dict[str, float] = {}
        for strat in strategies:
            pnl = float(pnl_by_strat.get(strat, 0.0))
            ret = pnl / max(1e-9, equity)
            ema_prev = ema_store.get(strat, 0.0)
            ema_curr = ALPHA * ret + (1 - ALPHA) * ema_prev
            ema_store[strat] = ema_curr

            var_prev = var_store.get(strat, 0.0)
            var_store[strat] = 0.5 * var_prev + 0.5 * (ret - ema_curr) ** 2
            std = math.sqrt(max(1e-12, var_store[strat]))

            explore = EXPLORATION * random.random()
            scores[strat] = max(0.0, ema_curr + 0.5 * std) + explore

        if not any(abs(score) > 1e-12 for score in scores.values()):
            scores = base_weights

        normalized = norm_scores(scores)
        capped = {
            strat: min(MAX_SHARE, max(MIN_SHARE, weight))
            for strat, weight in normalized.items()
        }
        total = sum(capped.values()) or 1.0
        final = {strat: weight / total for strat, weight in capped.items()}

        changed = False
        for strat, weight in final.items():
            if abs(weight - base_weights.get(strat, 0.0)) > 0.02:
                changed = set_weight(strat, weight) or changed

        if changed:
            pretty = {key: round(val, 3) for key, val in final.items()}
            print(f"[allocator] updated weights: {pretty}")
        else:
            print("[allocator] no material change")

        time.sleep(REFRESH)


if __name__ == "__main__":
    main()
