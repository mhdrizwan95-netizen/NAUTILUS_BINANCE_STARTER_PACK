# ops/make_synth_parquet.py
import numpy as np, pandas as pd, time, pathlib

N = 5000
ts0 = int(time.time_ns())
mid = 50000.0 + np.cumsum(np.random.normal(0, 2.0, N))  # wiggly mid
spread = np.clip(np.random.normal(8, 2, N), 3, 25)  # bp
bid = mid * (1 - spread / 2 / 1e4)
ask = mid * (1 + spread / 2 / 1e4)
bid_sz = np.random.uniform(0.2, 1.5, N)
ask_sz = np.random.uniform(0.2, 1.5, N)
trade_mask = np.random.rand(N) < 0.30
trade_px = np.where(trade_mask, mid + np.random.normal(0, 1.0, N), np.nan)
trade_sz = np.where(trade_mask, np.random.uniform(0.001, 0.02, N), np.nan)
aggr = np.where(trade_mask, np.random.choice([-1, 1], N), 0)
df = pd.DataFrame(
    {
        "ts_ns": ts0 + np.arange(N) * 1_000_000,  # 1ms steps
        "bid_px": bid,
        "ask_px": ask,
        "bid_sz": bid_sz,
        "ask_sz": ask_sz,
        "trade_px": trade_px,
        "trade_sz": trade_sz,
        "aggressor": aggr,
    }
)
out = pathlib.Path("data/processed")
out.mkdir(parents=True, exist_ok=True)
df.to_parquet(out / "synth_BTCUSDT_ticks.parquet")
print("Wrote", out / "synth_BTCUSDT_ticks.parquet")
