"""
Example script: emit mock metrics to the Deck API for testing dashboards.
"""
from __future__ import annotations

import random
import time

from ops.deck_metrics import push_metrics, push_strategy_pnl


def main() -> None:
    equity = 2000.0
    pnl_24h = 0.0
    drawdown_pct = 0.0
    tick_p50_ms = 60.0
    tick_p95_ms = 120.0
    error_rate_pct = 0.0

    while True:
        pnl_24h += random.uniform(-5, 7)
        equity = 2000.0 + pnl_24h
        push_metrics(
            equity_usd=equity,
            pnl_24h=pnl_24h,
            drawdown_pct=drawdown_pct,
            tick_p50_ms=tick_p50_ms,
            tick_p95_ms=tick_p95_ms,
            error_rate_pct=error_rate_pct,
            breaker={"equity": False, "venue": False},
        )
        push_strategy_pnl(
            {
                "scalp": random.uniform(-3, 3),
                "momentum": random.uniform(-4, 4),
                "trend": random.uniform(-2, 2),
                "event": random.uniform(-1, 5),
            }
        )
        time.sleep(5)


if __name__ == "__main__":
    main()
