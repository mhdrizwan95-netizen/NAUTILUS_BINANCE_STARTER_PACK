from pathlib import Path

import httpx
from loguru import logger

from .clock import SimClock
from .config import settings
from .driver import HistoricalDriver
from .execution import ExecutionModel
from .strategy_momentum import MomentumBreakout


def _train_if_due(last_train_ms: int, now_ms: int) -> int:
    period_ms = settings.TRAIN_CRON_MINUTES * 60 * 1000
    if last_train_ms == 0 or now_ms - last_train_ms >= period_ms:
        # trigger ml_service train
        try:
            with httpx.Client(timeout=60) as x:
                r = x.post(
                    f"{settings.ML_SERVICE}/train",
                    json={"n_states": 4, "promote": settings.PROMOTE},
                )
                logger.info(f"train -> {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.warning(f"train failed: {e}")
        return now_ms
    return last_train_ms


def _get_params(strategy: str, instrument: str, features: dict) -> dict:
    try:
        with httpx.Client(timeout=10) as x:
            r = x.get(
                f"{settings.PARAM_CONTROLLER}/param/{strategy}/{instrument}",
                params={**{f"features[{k}]": v for k, v in features.items()}},
            )
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"param get failed: {e}")
    return {
        "config_id": "na",
        "params": {},
        "policy_version": "na",
        "features_used": [],
    }


def run():
    logger.info("Backtest runner starting")
    symbol = settings.SYMBOLS.split(",")[0].strip()
    tf = settings.TIMEFRAME
    driver = HistoricalDriver(symbol, tf)
    clock = SimClock()
    execm = ExecutionModel(settings.FEE_BP, settings.SLIPPAGE_BP)
    strat = MomentumBreakout(instrument=symbol)

    equity = []
    times = []
    last_train_ms = 0
    step = 0

    while step < settings.MAX_STEPS:
        chunk = driver.feed_next_chunk()
        if chunk is None:
            logger.info("No more research data chunks; stopping.")
            break

        bars = chunk.copy()
        if "timestamp" not in bars.columns:
            bars.rename(columns={bars.columns[0]: "timestamp"}, inplace=True)
        bars.sort_values("timestamp", inplace=True)

        for _, row in bars.iterrows():
            ts = int(row["timestamp"])
            clock.tick(ts)
            last_train_ms = _train_if_due(last_train_ms, ts)

            bar = {
                "timestamp": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
            }

            # Simple features to feed controller + to ml_service.predict if needed
            # Here we demonstrate controller usage with a toy feature (scaled return)
            features = {"ret1": 0.0}
            if len(times) > 0:
                prev_close = equity[-1]["close_mtm"] if equity else bar["close"]
                features["ret1"] = (bar["close"] - prev_close) / max(prev_close, 1e-9)

            param_resp = _get_params("momentum_breakout", symbol.replace("/", "_"), features)
            params = param_resp.get("params", {})
            order = strat.on_bar(bar, params)
            execm.on_signal(order, bar)

            mtm = execm.mark_to_market(bar)
            equity_val = (
                equity[-1]["equity"] if equity else 100_000.0
            ) + mtm  # mark-to-market P&L on top of base equity
            equity.append({"t": ts, "equity": equity_val, "close_mtm": bar["close"]})
            times.append(ts)

        step += 1

    # Save results
    results_dir = Path("/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    eq = pd.DataFrame(equity)
    trades = pd.DataFrame(execm.trades)
    eq.to_csv(results_dir / "equity.csv", index=False)
    trades.to_csv(results_dir / "trades.csv", index=False)
    logger.info(f"Wrote results to {results_dir}")
