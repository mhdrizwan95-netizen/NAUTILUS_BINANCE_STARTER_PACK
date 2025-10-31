
import os, time
import pandas as pd
import numpy as np
from loguru import logger
from .sim import PrequentialSim
from .strategies import MomentumBreakout, MeanReversion
from .costs import simple_cost_model
from .metrics import summarize

def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Expect at minimum: timestamp(ms), open, high, low, close, volume
    if "timestamp" not in df.columns:
        df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")
    df.dropna(inplace=True)
    df.sort_values("timestamp", inplace=True)
    df.set_index("timestamp", inplace=True, drop=False)
    return df

def main():
    ds_path = os.getenv("DATASET", "/historical/sample.csv")
    retrain_min = int(os.getenv("RETRAIN_EVERY_MIN", "360"))
    step_minutes = int(os.getenv("STEP_MINUTES", "5"))
    exactly_once = os.getenv("EXACTLY_ONCE", "true").lower() == "true"
    cost_bps = float(os.getenv("COST_BPS", "1.0"))
    slip_bps_per_vol = float(os.getenv("SLIPPAGE_BPS_PER_VOL", "2.0"))

    df = load_dataset(ds_path)
    logger.info(f"Loaded dataset {ds_path} -> {len(df)} bars")

    # Build strategies (parameter schemas would normally come from YAML; we set defaults here)
    strat1 = MomentumBreakout(symbol="BTC/USDT")
    strat2 = MeanReversion(symbol="BTC/USDT")

    sim = PrequentialSim(
        df=df,
        bar_minutes=step_minutes,
        retrain_every_min=retrain_min,
        exactly_once=exactly_once,
        cost_fn=lambda trade: simple_cost_model(trade, cost_bps, slip_bps_per_vol)
    )

    # Attach strategies
    sim.add_strategy(strat1)
    sim.add_strategy(strat2)

    # Run
    ledger, trades = sim.run()
    report = summarize(trades)
    logger.info(f"Backtest done. Net={report['net_pnl']:.4f}, Sharpe={report['sharpe']:.2f}, MaxDD={report['max_dd']:.4f}")
    # Print concise summary
    print("SUMMARY:", report)

if __name__ == "__main__":
    main()
