# ops/pnl_collector.py
from __future__ import annotations
import os, asyncio, time, logging, httpx
from prometheus_client import Gauge
from ops.prometheus import REGISTRY

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Prometheus Gauges per venue
PNL_REALIZED = Gauge(
    "pnl_realized_total",
    "Realized PnL per venue (USD)",
    ["venue"],
    registry=REGISTRY,
    multiprocess_mode="max",
)
PNL_UNREALIZED = Gauge(
    "pnl_unrealized_total",
    "Unrealized PnL per venue (USD)",
    ["venue"],
    registry=REGISTRY,
    multiprocess_mode="max",
)
PNL_LAST_REFRESH = Gauge(
    "ops_pnl_last_refresh_epoch",
    "Unix time of last PnL refresh",
    registry=REGISTRY,
    multiprocess_mode="max",
)

async def _fetch_pnl(client: httpx.AsyncClient, base_url: str) -> dict:
    """Prefer /portfolio to avoid venue calls; fallback to /account_snapshot."""
    base = base_url.rstrip('/')
    try:
        r = await client.get(f"{base}/portfolio", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        pass
    try:
        r = await client.get(f"{base}/account_snapshot", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

async def pnl_collector_loop():
    """Continuously collect PnL from all engines."""
    endpoints = os.getenv("ENGINE_ENDPOINTS", "http://engine_binance:8003,http://engine_ibkr:8005").split(",")

    while True:
        try:
            async with httpx.AsyncClient() as client:
                results = await asyncio.gather(*[_fetch_pnl(client, e) for e in endpoints], return_exceptions=True)

            for e, res in zip(endpoints, results):
                if not isinstance(res, dict):
                    continue
                venue = e.split("//")[-1].split(":")[0].replace("engine_", "").upper()
                pnl = res.get("pnl") or {}
                realized = float(pnl.get("realized", 0.0))
                unrealized = float(pnl.get("unrealized", 0.0))
                PNL_REALIZED.labels(venue=venue).set(realized)
                PNL_UNREALIZED.labels(venue=venue).set(unrealized)

            PNL_LAST_REFRESH.set(time.time())
            logging.info(f"PnL updated for {len(endpoints)} venues")
        except Exception as e:
            logging.warning(f"PnL collector error: {e}")
        await asyncio.sleep(10)
