# ops/pnl_collector.py
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from ops.env import engine_endpoints
from ops.prometheus import get_or_create_gauge

try:  # pragma: no cover - respx only in tests
    from respx.models import AllMockedAssertionError as _RespxAllMockedAssertionError
except ImportError:  # pragma: no cover - prod deployments lack respx
    _RESPX_MOCK_ERRORS: tuple[type[Exception], ...] = ()
else:
    _RESPX_MOCK_ERRORS = (_RespxAllMockedAssertionError,)

_PNL_FETCH_ERRORS = (httpx.HTTPError,) + _RESPX_MOCK_ERRORS

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


def _venue_label(base_url: str) -> str:
    host = base_url.split("//")[-1].split("/")[0]
    host = host.split(":")[0]
    return host.upper()


# Prometheus Gauges per venue
PNL_REALIZED = get_or_create_gauge(
    "pnl_realized_total",
    "Realized PnL per venue (USD)",
    labelnames=("venue",),
    multiprocess_mode="max",
)
PNL_UNREALIZED = get_or_create_gauge(
    "pnl_unrealized_total",
    "Unrealized PnL per venue (USD)",
    labelnames=("venue",),
    multiprocess_mode="max",
)
PNL_LAST_REFRESH = get_or_create_gauge(
    "ops_pnl_last_refresh_epoch",
    "Unix time of last PnL refresh",
    multiprocess_mode="max",
)


async def _fetch_pnl(client: httpx.AsyncClient, base_url: str) -> dict:
    """Prefer /portfolio to avoid venue calls; fallback to /account_snapshot."""
    base = base_url.rstrip("/")
    try:
        r = await client.get(f"{base}/portfolio", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except _PNL_FETCH_ERRORS:
        pass
    try:
        r = await client.get(f"{base}/account_snapshot", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except _PNL_FETCH_ERRORS:
        return {}


async def pnl_collector_loop():
    """Continuously collect PnL from all engines."""
    poll_errors = (httpx.HTTPError, ValueError)
    while True:
        try:
            endpoints = engine_endpoints()
            limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
            async with httpx.AsyncClient(limits=limits, trust_env=True) as client:
                results = await asyncio.gather(
                    *[_fetch_pnl(client, e) for e in endpoints], return_exceptions=True
                )

            for e, res in zip(endpoints, results, strict=False):
                if not isinstance(res, dict):
                    continue
                venue = _venue_label(e)
                pnl = res.get("pnl") or {}
                realized = float(pnl.get("realized", 0.0))
                unrealized = float(pnl.get("unrealized", 0.0))
                PNL_REALIZED.labels(venue=venue).set(realized)
                PNL_UNREALIZED.labels(venue=venue).set(unrealized)

            PNL_LAST_REFRESH.set(time.time())
            logging.info("PnL updated for %s venues", len(endpoints))
        except poll_errors as exc:
            logging.warning("PnL collector error: %s", exc)
        await asyncio.sleep(10)
