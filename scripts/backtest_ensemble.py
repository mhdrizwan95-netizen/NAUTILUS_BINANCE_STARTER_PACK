#!/usr/bin/env python3
"""
Offline backtest for ensemble policy (HMM + MA).

Usage:
  python scripts/backtest_ensemble.py \
      --csv data/BTCUSDT_1m.csv \
      --hmm engine/models/hmm_policy.pkl \
      --symbol BTCUSDT \
      --quote 100 \
      --tp-bps 20 \
      --sl-bps 30 \
      --cooldown 30 \
      --min-conf 0.6 \
      --out reports/backtest_ensemble_BTCUSDT.json
"""

import math, json, pickle, argparse
import numpy as np, pandas as pd
from pathlib import Path
from train_hmm_policy import _read_csv, _rolling_features

def pct_to_price(px, bps):
    return px * (1 + bps / 10000.0)

def ma_confidence(fast, slow, price):
    """Confidence from normalized MA difference."""
    return min(1.0, abs((fast - slow) / price))

def backtest(cfg):
    Path(cfg.out).parent.mkdir(parents=True, exist_ok=True)

    # Load and prepare price data with MAs
    df = _read_csv(cfg.csv)
    df["ma_fast"] = df["price"].rolling(cfg.fast, min_periods=1).mean()
    df["ma_slow"] = df["price"].rolling(cfg.slow, min_periods=1).mean()
    df = df.dropna().reset_index(drop=True)

    # Load HMM model and get regime predictions
    with open(cfg.hmm, "rb") as f:
        model = pickle.load(f)

    # Get HMM features and predictions (after warmup)
    feats = _rolling_features(df["price"].values, df["volume"].values, window=120)
    if len(feats) > 120:
        feats = feats.iloc[120:].reset_index(drop=True)
        df = df.iloc[120:].reset_index(drop=True)
    else:
        print(f"Warning: Insufficient data for warmup window (120). Have {len(feats)} rows.")
        return

    X = feats.values
    probs = model.predict_proba(X)
    preds = model.model.predict(model.scaler.transform(X))
    n_states = probs.shape[1]

    # Map states to regimes by average return performance
    rets = df["price"].pct_change().fillna(0)
    df["state"] = preds
    avg_ret = df.groupby("state")["price"].pct_change().mean().fillna(0)

    # Sort states by return performance: worst→best
    order = np.argsort(avg_ret.values)
    state_to_regime = {}
    if len(order) >= 2:
        state_to_regime[order[0]] = "bear"      # worst performing
        state_to_regime[order[-1]] = "bull"     # best performing
    if len(order) >= 3:
        state_to_regime[order[1]] = "chop"      # neutral/mediocre

    df["regime"] = df["state"].map(state_to_regime)
    df["p_bull"] = probs[:, order[-1]] if len(order) > 1 else 0.5
    df["p_bear"] = probs[:, order[0]] if len(order) > 0 else 0.5
    df["p_chop"] = probs[:, order[1]] if len(order) > 2 else (probs[:, -1] if n_states == 1 else 0.5)

    # Simulate trading with ensemble logic
    pos, entry, balance, wins, losses = 0.0, 0.0, 0.0, 0, 0
    last_trade_ts = 0
    equity_curve = []

    for i, row in df.iterrows():
        ts, px = row.ts, row.price

        # Generate MA signals and confidence
        ma_side = "BUY" if row.ma_fast > row.ma_slow else "SELL"
        ma_conf = ma_confidence(row.ma_fast, row.ma_slow, px)

        # Generate HMM signals and confidence
        hmm_side = "BUY" if row.regime == "bull" else "SELL" if row.regime == "bear" else None
        hmm_conf = max(row.p_bull, row.p_bear) if isinstance(row.p_bull, (int, float)) and isinstance(row.p_bear, (int, float)) else 0.5

        # Calculate ensemble score
        score = 0
        if ma_side == "BUY":
            score += cfg.w_ma * ma_conf
        else:
            score -= cfg.w_ma * ma_conf

        if hmm_side == "BUY":
            score += cfg.w_hmm * hmm_conf
        elif hmm_side == "SELL":
            score -= cfg.w_hmm * hmm_conf

        # Check position exits
        if pos != 0:
            if pos > 0:  # Long position exits
                if px >= pct_to_price(entry, cfg.tp_bps):       # Take profit
                    pnl = (px - entry) * pos
                    balance += pnl; pos, entry = 0, 0; wins += 1
                elif px <= pct_to_price(entry, -cfg.sl_bps):   # Stop loss
                    pnl = (px - entry) * pos
                    balance += pnl; pos, entry = 0, 0; losses += 1
            else:  # Short position exits
                if px <= pct_to_price(entry, -cfg.tp_bps):     # Take profit
                    pnl = (entry - px) * abs(pos)
                    balance += pnl; pos, entry = 0, 0; wins += 1
                elif px >= pct_to_price(entry, cfg.sl_bps):    # Stop loss
                    pnl = (entry - px) * abs(pos)
                    balance += pnl; pos, entry = 0, 0; losses += 1

        # Cooldown check
        if ts - last_trade_ts < cfg.cooldown:
            equity_curve.append((ts, balance))
            continue

        # Consensus threshold check
        if abs(score) < cfg.min_conf:
            equity_curve.append((ts, balance))
            continue

        # Execute ensemble trade
        side = "BUY" if score > 0 else "SELL"

        # Apply slippage
        entry = px * (1 + cfg.slippage_bps/10000.0) if side == "BUY" else px * (1 - cfg.slippage_bps/10000.0)
        pos = cfg.quote / entry if side == "BUY" else -cfg.quote / entry
        last_trade_ts = ts

        # Record unrealized P&L
        equity_curve.append((ts, balance + pos * (px - entry)))

    # Save equity curve
    eq_df = pd.DataFrame(equity_curve, columns=["ts", "equity_usd"])
    eq_df["date"] = pd.to_datetime(eq_df["ts"], unit="s")
    csv_out = Path(cfg.out).with_suffix(".csv")
    eq_df.to_csv(csv_out, index=False)

    # Calculate performance metrics
    returns = eq_df["equity_usd"].diff().fillna(0)
    mean, std = returns.mean(), returns.std()
    sharpe = (mean / (std + 1e-9)) * math.sqrt(252*24*60) if std else 0.0
    drawdown = (eq_df["equity_usd"].cummax() - eq_df["equity_usd"]).max()

    summary = dict(
        symbol=cfg.symbol,
        quote=cfg.quote,
        trades=wins + losses,
        wins=wins,
        losses=losses,
        winrate=(wins / (wins + losses)) if (wins + losses) > 0 else 0,
        pnl_usd=round(balance, 2),
        sharpe=round(float(sharpe), 3),
        max_drawdown_usd=round(float(drawdown), 2),
        final_equity_usd=round(balance, 2),
        config={
            "fast": cfg.fast,
            "slow": cfg.slow,
            "weights": {"ma_v1": cfg.w_ma, "hmm_v1": cfg.w_hmm},
            "min_conf": cfg.min_conf,
            "tp_bps": cfg.tp_bps,
            "sl_bps": cfg.sl_bps,
            "cooldown": cfg.cooldown,
            "slippage_bps": cfg.slippage_bps
        }
    )

    with open(cfg.out, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"\nEquity curve saved to: {csv_out}")

def main():
    ap = argparse.ArgumentParser(description="Backtest HMM+MA ensemble strategy")
    ap.add_argument("--csv", required=True, help="Path to price CSV with ts,price,volume")
    ap.add_argument("--hmm", required=True, help="Path to trained HMM model .pkl")
    ap.add_argument("--symbol", required=True, help="Trading symbol")
    ap.add_argument("--quote", type=float, default=100, help="Quote amount per trade")
    ap.add_argument("--fast", type=int, default=9, help="Fast MA window")
    ap.add_argument("--slow", type=int, default=21, help="Slow MA window")
    ap.add_argument("--tp-bps", type=float, default=20, help="Take profit in basis points")
    ap.add_argument("--sl-bps", type=float, default=30, help="Stop loss in basis points")
    ap.add_argument("--cooldown", type=int, default=30, help="Cooldown between trades (seconds)")
    ap.add_argument("--slippage-bps", type=float, default=3, help="Trading slippage in basis points")
    ap.add_argument("--min-conf", type=float, default=0.6, help="Minimum consensus confidence")
    ap.add_argument("--w-ma", type=float, default=0.4, help="Weight for MA signals")
    ap.add_argument("--w-hmm", type=float, default=0.6, help="Weight for HMM signals")
    ap.add_argument("--out", default="reports/backtest_ensemble.json", help="Output JSON path")

    args = ap.parse_args()
    backtest(args)

if __name__ == "__main__":
    main()
