# Offline backtesting utilities

This directory contains a small replay engine and a set of scripts that allow
running strategy modules against historical Binance klines that live on disk.
All tools use `backtests/engine.py` which loads CSV/Parquet files, replays the
bars in chronological order, and invokes the relevant strategy's `handle_tick`
method exactly like the production runtime.

The examples below assume you have exported klines in the standard Binance
format (`open_time,open,high,low,close,volume,...`) or in the lightweight
`ts,price,volume` format used by the HMM training pipeline. Paths may point to
either CSV or Parquet files.

## Trend following

```
python backtests/trend_follow_backtest.py \
    --symbol BTCUSDT \
    --data 1h=data/BTCUSDT_1h.parquet \
    --data 4h=data/BTCUSDT_4h.parquet \
    --data 1d=data/BTCUSDT_1d.parquet \
    --warmup 300 \
    --output backtests/results/trend.json
```

The script requires one dataset per configured timeframe (primary, secondary
and regime). The resulting JSON file contains the trade ledger and a summary of
PnL statistics.

## HMM ensemble (HMM + MA fusion)

```
python scripts/backtest_ensemble.py \
    --csv data/BTCUSDT_1m.csv \
    --hmm engine/models/hmm_policy.pkl \
    --symbol BTCUSDT \
    --quote 100 \
    --out reports/backtest_ensemble.json
```

This replays the ensemble signal generator with the supplied HMM policy and
produces both a JSON performance summary and an equity curve CSV.

## Scalping

```
python backtests/scalping_backtest.py \
    --symbol BTCUSDT \
    --data data/BTCUSDT_1m.parquet \
    --spread-bps 5 \
    --depth-usd 75000 \
    --output backtests/results/scalp.json
```

The scalping harness synthesizes a simple order book from the candle close and
records every emitted signal.

## Momentum breakout

```
python backtests/momentum_backtest.py \
    --symbol BTCUSDT \
    --data data/BTCUSDT_1m.csv \
    --quote 200 \
    --output backtests/results/momentum.json
```

This counts all breakout alerts along with basic metadata (price, timestamp,
volume) for further analysis.

## Engine reuse

If you need a custom backtest, import `BacktestEngine` and configure one or
more `FeedConfig` objects to point at your local datasets:

```python
from backtests.engine import BacktestEngine, FeedConfig
from engine.strategies.trend_follow import TrendStrategyModule, load_trend_config

cfg = load_trend_config()
feed = FeedConfig(symbol="BTCUSDT", timeframe="1h", path=Path("data/BTCUSDT_1h.csv"))
engine = BacktestEngine(
    feeds=[feed],
    strategy_factory=lambda client, clock: TrendStrategyModule(cfg, client=client, clock=clock),
    patch_executor=True,
)

for step in engine.run():
    print(step.event.timestamp_ms, step.response)

orders = [order for order in engine.recorded_orders]
```

Setting `patch_executor=True` (or exporting `BACKTEST_PATCH_EXECUTOR=1`) swaps in a
recording executor that captures every strategy submission attempt instead of
touching the live router. Recorded orders include symbol, side, market, size,
metadata, and the original signal payload so downstream PnL/cooldown analysis
can replay the decisions offline.

`FeedConfig` supports custom timestamp/price/volume column names and automatically
converts second-based timestamps to milliseconds for compatibility with the live
strategy modules.
