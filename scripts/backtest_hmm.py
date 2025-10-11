#!/usr/bin/env python3
"""
Offline backtest scorer for HMM or any signal policy.

Usage:
  python scripts/backtest_hmm.py \
    --csv data/BTCUSDT_1m.csv \
    --model engine/models/hmm_policy.pkl \
    --symbol BTCUSDT \
    --quote 100 \
    --tp-bps 20 \
    --sl-bps 30 \
    --cooldown 30 \
    --slippage-bps 3 \
    --out reports/backtest_BTCUSDT.json

Outputs:
  - backtest_equity.csv (timestamp, equity_usd)
  - summary.json (returns, sharpe, drawdown, trades)
"""

import os, math, json, pickle, argparse
import numpy as np, pandas as pd
from datetime import datetime
from pathlib import Path
from train_hmm_policy import _read_csv, _rolling_features

def pct_to_price(px, bps):
    return px * (1 + bps / 10000.0)

def backtest(cfg):
    Path(cfg.out).parent.mkdir(parents=True, exist_ok=True)

    # Load trained model
    with open(cfg.model, "rb") as f:
        mdl = pickle.load(f)

    # Load and prepare price data
    df = _read_csv(cfg.csv)
    feats = _rolling_features(df["price"].values, df["volume"].values, window=120)
    df = df.iloc[120:].reset_index(drop=True)
    feats = feats.iloc[120:].reset_index(drop=True)

    # Get HMM state predictions
    X = feats.values
    preds = mdl.model.predict(mdl.scaler.transform(X))

    # Map states to regimes by average return performance
    rets = df["price"].pct_change().fillna(0)
    df["state"] = preds
    avg_ret = df.groupby("state")["price"].pct_change().mean().fillna(0)
    order = np.argsort(avg_ret.values)  # lowest→highest returns

    # Map states to regimes: bear, chop, bull
    state_to_regime = {}
    n_states = len(order)

    if n_states >= 2:
        state_to_regime[order[0]] = "bear"      # worst performing state
        state_to_regime[order[-1]] = "bull"     # best performing state
    if n_states >= 3:
        state_to_regime[order[1]] = "chop"      # neutral/mediocre state

    df["regime"] = df["state"].map(state_to_regime)

    # Simulate trades with identical logic to live engine
    balance = 0.0
    pos = 0.0
    entry = 0.0
    last_trade_ts = 0
    equity_curve = []
    wins, losses = 0, 0

    for i in range(len(df)):
        ts = df.loc[i, "ts"]
        px = df.loc[i, "price"]
        regime = df.loc[i, "regime"]

        if math.isnan(px):
            continue

        # Check open position for exit conditions
        if pos != 0:
            if pos > 0:  # Long position
                if px >= pct_to_price(entry, cfg.tp_bps):
                    # Take profit
                    pnl = (px - entry) * pos
                    balance += pnl
                    pos, entry = 0, 0
                    wins += 1
                elif px <= pct_to_price(entry, -cfg.sl_bps):
                    # Stop loss
                    pnl = (px - entry) * pos
                    balance += pnl
                    pos, entry = 0, 0
                    losses += 1
            else:  # Short position
                if px <= pct_to_price(entry, -cfg.tp_bps):
                    # Take profit (short cover)
                    pnl = (entry - px) * abs(pos)
                    balance += pnl
                    pos, entry = 0, 0
                    wins += 1
                elif px >= pct_to_price(entry, cfg.sl_bps):
                    # Stop loss (forced cover)
                    pnl = (entry - px) * abs(pos)
                    balance += pnl
                    pos, entry = 0, 0
                    losses += 1

        # Cooldown check (identical to runtime)
        if ts - last_trade_ts < cfg.cooldown:
            equity_curve.append((ts, balance))
            continue

        # Entry conditions based on regime
        if pos == 0 and regime == "bull":
            # Enter long with slippage
            entry = px * (1 + cfg.slippage_bps/10000.0)
            pos = cfg.quote / entry
            last_trade_ts = ts
        elif pos == 0 and regime == "bear":
            # Enter short with slippage
            entry = px * (1 - cfg.slippage_bps/10000.0)
            pos = -cfg.quote / entry
            last_trade_ts = ts

        # Record equity (unrealized P&L)
        equity_curve.append((ts, balance + pos * (px - entry)))

    # Save equity curve
    equity = pd.DataFrame(equity_curve, columns=["ts","equity_usd"])
    equity["date"] = pd.to_datetime(equity["ts"], unit="s")
    csv_out = Path(cfg.out).with_suffix(".csv")
    equity.to_csv(csv_out, index=False)

    # Calculate performance metrics
    returns = equity["equity_usd"].diff().fillna(0)
    mean, std = returns.mean(), returns.std()
    sharpe = (mean / (std + 1e-9)) * math.sqrt(252*24*60) if std else 0.0  # Annualized
    drawdown = (equity["equity_usd"].cummax() - equity["equity_usd"]).max()

    summary = dict(
        symbol=cfg.symbol,
        quote=cfg.quote,
        trades=wins + losses,
        wins=wins,
        losses=losses,
        winrate=(wins / (wins + losses)) if (wins + losses) > 0 else 0,
        pnl_usd=round(balance, 2),
        Sharpe=float(sharpe),
        max_drawdown_usd=round(float(drawdown), 2),
        final_equity_usd=round(balance, 2),
    )

    # Save summary
    with open(cfg.out, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"\nEquity curve saved to: {csv_out}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to price CSV with ts,price,volume")
    ap.add_argument("--model", required=True, help="Path to trained HMM model .pkl file")
    ap.add_argument("--symbol", required=True, help="Trading symbol")
    ap.add_argument("--quote", type=float, default=100, help="Quote amount per trade (USDT)")
    ap.add_argument("--tp-bps", type=float, default=20, help="Take profit in basis points")
    ap.add_argument("--sl-bps", type=float, default=30, help="Stop loss in basis points")
    ap.add_argument("--cooldown", type=int, default=30, help="Cooldown between trades (seconds)")
    ap.add_argument("--slippage-bps", type=float, default=3, help="Trading slippage in basis points")
    ap.add_argument("--out", default="reports/backtest.json", help="Output path for summary JSON")
    args = ap.parse_args()
    backtest(args)

if __name__ == "__main__":
    main()
