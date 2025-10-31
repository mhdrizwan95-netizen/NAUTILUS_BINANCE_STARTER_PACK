# ops/strategy_tracker.py
import time, json, math, asyncio, httpx, logging
from statistics import mean, pstdev
from pathlib import Path
from ops.env import engine_endpoints

REGISTRY_PATH = Path("ops/strategy_registry.json")

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Prometheus metrics for strategy performance monitoring
from prometheus_client import Gauge
from ops.prometheus import REGISTRY

SHARPE_GAUGE = Gauge(
    "strategy_sharpe",
    "Live Sharpe ratio per strategy",
    ["model"],
    registry=REGISTRY,
    multiprocess_mode="max",
)
DD_GAUGE = Gauge(
    "strategy_drawdown",
    "Live drawdown per strategy",
    ["model"],
    registry=REGISTRY,
    multiprocess_mode="max",
)
REALIZED_GAUGE = Gauge(
    "strategy_realized_pnl",
    "Realized PnL per strategy",
    ["model"],
    registry=REGISTRY,
    multiprocess_mode="max",
)

def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception:
            pass
    return {"current_model": None}

def save_registry(d: dict):
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(REGISTRY_PATH)

async def fetch_strategy_metrics(base_url: str, current_model: str | None = None) -> dict:
    """
    Scrape strategy-tagged PnL metrics from engine /metrics endpoint.
    Expects Prometheus format like: pnl_realized_total{venue="BINANCE",model="hmm_v1"} 120.0
    """
    try:
        # Get metrics from engine
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base_url.rstrip('/')}/metrics", timeout=5.0)
        r.raise_for_status()
        txt = r.text
    except Exception:
        return {}

    # Crude scrape: extract metrics labelled by model_tag if exported
    data = {}
    for line in txt.splitlines():
        if "pnl_realized_total" in line and "model=" in line and "venue=" in line:
            # e.g. pnl_realized_total{venue="BINANCE",model="hmm_v1"} 120.0
            model = line.split('model="')[1].split('"')[0]
            val = float(line.split()[-1])
            data.setdefault(model, {"realized": val})

        if "pnl_unrealized_total" in line and "model=" in line:
            model = line.split('model="')[1].split('"')[0]
            val = float(line.split()[-1])
            if model in data:
                data[model]["unrealized"] = val
    # Fallback: if no model-labelled metrics were found, attribute aggregate engine PnL to current model
    if not data and current_model:
        realized = None
        unrealized = None
        for line in txt.splitlines():
            if line.startswith("pnl_realized_total ") and ' {' not in line:
                try:
                    realized = float(line.split()[-1])
                except Exception:
                    pass
            if line.startswith("pnl_unrealized_total ") and ' {' not in line:
                try:
                    unrealized = float(line.split()[-1])
                except Exception:
                    pass
        if realized is not None or unrealized is not None:
            data[current_model] = {}
            if realized is not None:
                data[current_model]["realized"] = realized
            if unrealized is not None:
                data[current_model]["unrealized"] = unrealized

    return data

async def strategy_tracker_loop():
    """
    Continuously collect performance metrics from all engines and update registry.
    Maintains rolling performance statistics for strategy comparison.
    """
    engines = engine_endpoints()
    registry = load_registry()
    metrics: dict[str, list[float]] = {}
    samples = 0

    while True:
        try:
            all_data = {}
            current_model = registry.get("current_model")
            for e in engines:
                data = await fetch_strategy_metrics(e, current_model=current_model)
                for m, vals in data.items():
                    all_data.setdefault(m, {}).update(vals)

            # Update rolling metrics for each strategy
            for model, vals in all_data.items():
                pnl = vals.get("realized", 0.0)
                unrl = vals.get("unrealized", 0.0)
                total_return = pnl + unrl  # Simple approximation

                # Track rolling samples (last 60 samples = 10 minutes at 10s intervals)
                metrics.setdefault(model, []).append(total_return)
                if len(metrics[model]) > 60:
                    metrics[model].pop(0)

                arr = metrics[model]
                reg = registry.get(model, {}).copy()

                # Maintain rolling samples for governance stats
                historic = reg.get("samples", [])
                if isinstance(historic, list):
                    new_samples = (historic + [total_return])[-60:]
                else:
                    new_samples = [total_return]
                reg["samples"] = new_samples
                reg["realized"] = float(round(pnl, 6))
                reg["last_pnl"] = float(round(total_return, 6))

                if len(arr) >= 5:
                    mu = mean(arr)
                    sigma = pstdev(arr) or 1e-6  # Avoid division by zero
                    sharpe = mu / sigma if sigma > 0 else 0.0
                    dd = max(arr) - min(arr) if len(arr) > 1 else 0.0

                    reg["sharpe"] = float(sharpe)
                    reg["drawdown"] = float(dd)

                    SHARPE_GAUGE.labels(model=model).set(float(sharpe))
                    DD_GAUGE.labels(model=model).set(float(dd))

                REALIZED_GAUGE.labels(model=model).set(float(pnl))

                registry[model] = reg

            save_registry(registry)
            samples += 1
            if samples % 6 == 0:  # Every 60s at 10s intervals
                logging.info(f"[StrategyTracker] Updated {len(all_data)} models; current: {registry.get('current_model')}")
        except Exception as e:
            logging.warning(f"Strategy tracker error: {e}")

        await asyncio.sleep(10)
