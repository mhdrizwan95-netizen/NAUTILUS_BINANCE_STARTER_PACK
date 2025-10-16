"""
Executor daemon

- Default mode: heartbeat-only (metrics + engine ping)
- Trade mode: lightweight trading loop which probes symbols and places
  market orders through the engine based on simple sizing and limits.

Use: `python -u ops/main.py trade` to start the trading loop.
"""

from __future__ import annotations

import asyncio
import os
import time
import sys
from collections import defaultdict
from typing import Any, Dict, List

import httpx
from prometheus_client import start_http_server, Gauge, Counter

# Reuse the probing utilities for simple execution
from ops.auto_probe import (
    RateLimiter,
    get_universe,
    probe_symbol,
    env_b,
    env_f,
    env_i,
)


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
    print(f"[executor] metrics listening on :{METRICS_PORT}", flush=True)
    print(f"[executor] engine at {ENGINE_URL}", flush=True)

    async with httpx.AsyncClient() as client:
        # Initial ping fast, then settle into interval
        while True:
            await ping_engine(client)
            await asyncio.sleep(PING_INTERVAL_SEC)


async def trade() -> None:
    """Start the lightweight trading loop.

    Environment knobs:
    - ENGINE_URL: engine base URL
    - TRADE_SYMBOLS: CSV list; if empty use engine /universe
    - DRY_RUN: if true, simulate without submitting
    - PROBE_USDT: per-order quote size (min notional respected)
    - MAX_SLIP_BP: soft slippage guard for logging
    - MAX_ORDERS_PER_MIN: global rate limit
    - MAX_PARALLEL_ORDERS: concurrency
    - PROBE_COOLDOWN_SEC: min seconds between probes per symbol
    - EXEC_INTERVAL_SEC: loop cadence
    """

    # Metrics server (shared)
    start_http_server(METRICS_PORT)
    EXECUTOR_UP.set(1)
    print(f"[executor] metrics listening on :{METRICS_PORT}", flush=True)
    print(f"[executor] engine at {ENGINE_URL}", flush=True)

    # Config
    dry_run = env_b("DRY_RUN", False)
    probe_usdt = env_f("PROBE_USDT", 30.0)
    max_slip_bp = env_f("MAX_SLIP_BP", 120.0)
    max_per_min = env_i("MAX_ORDERS_PER_MIN", 20)
    max_parallel = env_i("MAX_PARALLEL_ORDERS", 3)
    cooldown_sec = env_i("PROBE_COOLDOWN_SEC", 90)

    # Symbols
    explicit = os.getenv("TRADE_SYMBOLS") or os.getenv("SYMBOLS")
    if explicit:
        symbols: List[str] = [s.strip() for s in explicit.split(",") if s.strip()]
    else:
        symbols = await get_universe(ENGINE_URL)

    if not symbols:
        print("[executor] No symbols configured; exiting.")
        return

    print(f"[executor] trade loop starting; dry_run={dry_run} symbols={symbols}")

    limiter = RateLimiter(max_per_min)
    sem = asyncio.Semaphore(max_parallel)
    last_probe_ts: Dict[str, float] = defaultdict(lambda: 0.0)

    try:
        while True:
            # Kick an engine health ping on each loop
            try:
                async with httpx.AsyncClient() as client:
                    await ping_engine(client)
            except Exception:
                pass

            tasks = [
                probe_symbol(
                    ENGINE_URL,
                    sym,
                    probe_usdt,
                    max_slip_bp,
                    cooldown_sec,
                    limiter,
                    sem,
                    last_probe_ts,
                    dry_run,
                )
                for sym in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Summarize
            filled = 0
            errs = 0
            for r in results:
                if isinstance(r, Exception):
                    errs += 1
                    PROBE_ERRORS.inc()
                    continue
                if r.get("error"):
                    errs += 1
                    PROBE_ERRORS.inc()
                elif r.get("status") == "FILLED":
                    filled += 1
                    PROBES_FILLED.inc()
                # Count any attempt
                if not r.get("skipped"):
                    PROBES_SUBMITTED.inc()

            print(
                f"[executor] tick… symbols={len(symbols)} filled={filled} errors={errs}",
                flush=True,
            )

            await asyncio.sleep(EXEC_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("[executor] trade loop shutdown", file=sys.stderr)
        return


if __name__ == "__main__":
    # Mode select: default heartbeat; `trade` starts the trading loop
    mode = (sys.argv[1].lower() if len(sys.argv) > 1 else "heartbeat")
    try:
        if mode == "trade":
            asyncio.run(trade())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("[executor] shutdown", file=sys.stderr)
        sys.exit(0)
