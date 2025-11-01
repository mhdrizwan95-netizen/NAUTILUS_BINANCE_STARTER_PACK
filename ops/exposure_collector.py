# ops/exposure_collector.py
from __future__ import annotations
import asyncio, time, logging, os
from prometheus_client import Gauge
from ops.prometheus import REGISTRY
from ops.aggregate_exposure import aggregate_exposure, _parse_endpoints

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
)

EXPOSURE_GAUGE = Gauge(
    "exposure_usd",
    "USD exposure per symbol",
    ["symbol"],
    registry=REGISTRY,
    multiprocess_mode="max",
)
LAST_REFRESH = Gauge(
    "ops_exposure_last_refresh_epoch",
    "Unix time of last exposure refresh",
    registry=REGISTRY,
    multiprocess_mode="max",
)


def _engine_endpoints() -> list[str]:
    raw = os.getenv(
        "ENGINE_ENDPOINTS", "http://engine_binance:8003,http://engine_ibkr:8005"
    )
    return _parse_endpoints(raw)


async def exposure_collector_loop():
    """Continuously aggregates exposure across venues and exports to Prometheus."""
    tickers = os.getenv("OPS_IBKR_TICKERS", "AAPL,MSFT,NVDA,TSLA")

    while True:
        try:
            endpoints = _engine_endpoints()
            if not endpoints:
                logging.warning("Exposure collector: no engine endpoints configured")
                await asyncio.sleep(10)
                continue
            agg = await aggregate_exposure(",".join(endpoints), tickers)
            ts = time.time()
            for sym, vals in agg.by_symbol.items():
                EXPOSURE_GAUGE.labels(symbol=sym).set(vals["exposure_usd"])
            LAST_REFRESH.set(ts)
            try:
                total = sum(
                    float(v.get("exposure_usd", 0.0)) for v in agg.by_symbol.values()
                )
                logging.info(
                    f"Exposure updated: symbols={len(agg.by_symbol)} total={total:.2f} USD"
                )
            except Exception:
                pass
        except Exception as e:
            logging.warning(f"Exposure collector error: {e}")
        await asyncio.sleep(10)  # refresh every 10s
