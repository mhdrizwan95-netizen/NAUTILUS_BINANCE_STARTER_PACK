"""
Executor daemon

- Default mode: heartbeat-only (metrics + engine ping)
- Trade mode: lightweight trading loop which probes symbols and places
  market orders through the engine based on simple sizing and limits.

Use: `python -u ops/main.py trade` to start the trading loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List

import httpx
from prometheus_client import Counter, Gauge, start_http_server

# Reuse the probing utilities for simple execution
from ops.auto_probe import (
    CircuitBreaker,
    RateLimiter,
    env_b,
    env_f,
    env_i,
    fetch_all_prices,
    get_universe,
    probe_symbol,
)

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

LOGGER = logging.getLogger("ops.executor")


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    payload = json.dumps({"event": event, **fields}, default=str)
    log_fn = getattr(LOGGER, level.lower(), LOGGER.info)
    log_fn(payload)


ENGINE_URL = os.getenv("ENGINE_URL", "http://engine_binance:8003").rstrip("/")
METRICS_PORT = int(os.getenv("EXEC_METRICS_PORT", "9102"))
PING_INTERVAL_SEC = int(os.getenv("EXEC_PING_INTERVAL_SEC", "5"))
EXEC_INTERVAL_SEC = int(os.getenv("EXEC_INTERVAL_SEC", "2"))

# Basic executor metrics
EXECUTOR_UP = Gauge("executor_up", "Executor process up (set to 1 on start)")
LAST_PING_EPOCH = Gauge("executor_last_ping_epoch", "Unix time of last engine ping")
ENGINE_SNAPSHOT_LOADED = Gauge("engine_snapshot_loaded", "Engine snapshot_loaded flag (1/0)")
PING_ERRORS = Counter("executor_ping_errors_total", "Total engine ping errors")

# Trade loop metrics (coarse)
PROBES_SUBMITTED = Counter("probe_submissions_total", "Total probes attempted")
PROBES_FILLED = Counter("probe_filled_total", "Total probes filled")
PROBE_ERRORS = Counter("probe_errors_total", "Total probe errors")

# Symbol feed metric
EXEC_SYMBOLS_SAMPLED = Gauge(
    "exec_symbols_sampled", "Symbols probed this round", labelnames=["job"]
)


async def ping_engine(client: httpx.AsyncClient) -> None:
    try:
        resp = await client.get(f"{ENGINE_URL}/health", timeout=5.0)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        snap_ok = 1 if bool(data.get("snapshot_loaded")) else 0
        ENGINE_SNAPSHOT_LOADED.set(snap_ok)
        LAST_PING_EPOCH.set(time.time())
    except Exception:
        PING_ERRORS.inc()


async def main() -> None:
    # Start metrics server
    start_http_server(METRICS_PORT)
    EXECUTOR_UP.set(1)
    log_event("executor.metrics_start", port=METRICS_PORT)
    log_event("executor.engine_target", engine_url=ENGINE_URL)

    client_limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    client_timeout = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

    async with httpx.AsyncClient(
        timeout=client_timeout, limits=client_limits, trust_env=True
    ) as client:
        # Initial ping fast, then settle into interval
        while True:
            await ping_engine(client)
            await asyncio.sleep(PING_INTERVAL_SEC)


async def trade() -> None:
    """Start the lightweight trading loop with storm-proof architecture.

    Environment knobs:
    - ENGINE_URL: engine base URL
    - DRY_RUN: if true, simulate without submitting
    - PROBE_USDT: per-order quote size (min notional respected)
    - EXEC_SYMBOLS_PER_ROUND: max symbols processed per round (default: 1)
    - EXEC_INTERVAL_SEC: loop cadence with jitter
    - Circuit Breaker parameters: EXEC_ERR_THRESHOLD, EXEC_ERR_WINDOW_SEC, EXEC_COOLDOWN_SEC
    """

    # Metrics server (shared)
    start_http_server(METRICS_PORT)
    EXECUTOR_UP.set(1)
    log_event("executor.metrics_start", port=METRICS_PORT)
    log_event("executor.engine_target", engine_url=ENGINE_URL)

    # Config with storm-proof defaults
    dry_run = env_b("DRY_RUN", False)
    probe_usdt = env_f("PROBE_USDT", 30.0)
    max_slip_bp = env_f("MAX_SLIP_BP", 120.0)
    max_per_min = env_i("MAX_ORDERS_PER_MIN", 3)
    max_parallel = env_i("MAX_PARALLEL_ORDERS", 1)
    cooldown_sec = env_i("PROBE_COOLDOWN_SEC", 45)

    # Get symbols
    explicit = os.getenv("TRADE_SYMBOLS") or os.getenv("SYMBOLS")
    if explicit:
        symbols: List[str] = [s.strip() for s in explicit.split(",") if s.strip()]
    else:
        # Fetch symbols using temp client since we don't have shared one yet
        async with httpx.AsyncClient(timeout=10.0):
            symbols = await get_universe(ENGINE_URL)

    if not symbols:
        log_event("executor.no_symbols", level="warning")
        return

    log_event(
        "executor.trade_start",
        dry_run=dry_run,
        symbol_count=len(symbols),
        probe_usdt=probe_usdt,
    )

    # Initialize storm-proof components
    limiter = RateLimiter(max_per_min)
    sem = asyncio.Semaphore(max_parallel)
    last_probe_ts: Dict[str, float] = defaultdict(lambda: 0.0)

    # Circuit breaker with environment-configurable thresholds
    breaker = CircuitBreaker(
        err_threshold=env_i("EXEC_ERR_THRESHOLD", 3),  # Trip on 3 errors
        window_sec=env_i("EXEC_ERR_WINDOW_SEC", 20),  # In 20 second window
        cooldown_sec=env_i("EXEC_COOLDOWN_SEC", 180),  # Cool down for 3 minutes
    )

    # Long-lived HTTP client with connection pooling
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=10)
    timeout = httpx.Timeout(connect=6.0, read=12.0, write=12.0, pool=12.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=True) as client:
            for r in range(99999):  # Infinite rounds, will be interrupted
                # Step 1: Fetch ALL prices in one round-trip (O(1) vs O(symbols))
                price_map = await fetch_all_prices(ENGINE_URL, client)

                # Step 2: Bound work per round (physically prevents storms)
                # - At most EXEC_SYMBOLS_PER_ROUND symbols processed per round
                # - Circuit breaker skips entire round if engine is stressed
                # - Least-recently-probed symbols get priority
                max_per_round = env_i("EXEC_SYMBOLS_PER_ROUND", 1)
                pick = []
                for sym in sorted(symbols, key=lambda z: last_probe_ts.get(z, 0.0)):
                    if len(pick) >= max_per_round:
                        break
                    pick.append(sym)

                # Step 3: Only probe selected symbols (use shared client, batched prices)
                tasks = [
                    probe_symbol(
                        client=client,
                        engine_base=ENGINE_URL,
                        symbol=sym,
                        quote_usdt=probe_usdt,
                        slip_bps_max=max_slip_bp,
                        cooldown_sec=cooldown_sec,
                        limiter=limiter,
                        sem=sem,
                        last_probe_ts=last_probe_ts,
                        dry_run=dry_run,
                        price_map=price_map,
                        breaker=breaker,
                    )
                    for sym in pick
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Step 4: Compact round summary with breaker status
                ok = sum(1 for r in results if r.get("status") == "FILLED")
                errs = sum(1 for r in results if "error" in r)
                skipped = sum(1 for r in results if r.get("skipped"))
                log_event(
                    "executor.round_summary",
                    round=r + 1,
                    symbols=len(pick),
                    filled=ok,
                    errors=errs,
                    skipped=skipped,
                    breaker="open" if breaker.open else "closed",
                )

                # Step 5: Pace rounds with jitter (prevents synchronization)
                base_interval = env_i("EXEC_INTERVAL_SEC", 12)
                jitter = env_f("EXEC_JITTER", 0.40)
                interval = base_interval * (1.0 + random.uniform(-jitter, jitter))
                await asyncio.sleep(interval)

    except KeyboardInterrupt:
        log_event("executor.trade_interrupt", level="warning")
        return


if __name__ == "__main__":
    # Mode select: default heartbeat; `trade` starts the trading loop
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "heartbeat"
    try:
        if mode == "trade":
            asyncio.run(trade())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        log_event("executor.shutdown", level="warning")
        sys.exit(0)
