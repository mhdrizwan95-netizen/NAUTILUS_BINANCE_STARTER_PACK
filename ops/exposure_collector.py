# ops/exposure_collector.py
from __future__ import annotations
import asyncio, time, logging, os
from prometheus_client import Gauge
from ops.aggregate_exposure import aggregate_exposure

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Dynamic gauge registry
GAUGES: dict[str, Gauge] = {}
LAST_REFRESH = Gauge("ops_exposure_last_refresh_epoch", "Unix time of last exposure refresh")

async def exposure_collector_loop():
    """Continuously aggregates exposure across venues and exports to Prometheus."""
    endpoints = os.getenv("ENGINE_ENDPOINTS", "http://engine_binance:8003,http://engine_ibkr:8005")
    tickers = os.getenv("OPS_IBKR_TICKERS", "AAPL,MSFT,NVDA,TSLA")

    while True:
        try:
            agg = await aggregate_exposure(endpoints, tickers)
            ts = time.time()
            for sym, vals in agg.by_symbol.items():
                gauge = GAUGES.get(sym)
                if gauge is None:
                    gauge = Gauge("exposure_usd", "USD exposure per symbol", ["symbol"])
                    GAUGES[sym] = gauge
                gauge.labels(symbol=sym).set(vals["exposure_usd"])
            LAST_REFRESH.set(ts)
            logging.info(".2f")
        except Exception as e:
            logging.warning(f"Exposure collector error: {e}")
        await asyncio.sleep(10)  # refresh every 10s
