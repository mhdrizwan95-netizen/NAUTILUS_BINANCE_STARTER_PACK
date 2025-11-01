#!/usr/bin/env python3
"""Offline backtest for the HMM + MA ensemble strategy using local klines."""

from __future__ import annotations

import argparse
import json
import math
import pickle
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from backtests.engine import BacktestEngine, FeedConfig

from train_hmm_policy import _read_csv, _rolling_features


def pct_to_price(px: float, bps: float) -> float:
    return px * (1 + bps / 10000.0)


@dataclass
class BacktestConfig:
    csv: Path
    hmm: Path
    symbol: str
    timeframe: str
    quote: float
    fast: int
    slow: int
    tp_bps: float
    sl_bps: float
    cooldown: float
    min_conf: float
    w_ma: float
    w_hmm: float
    slippage_bps: float
    warmup: int = 180


def _prepare_metrics(cfg: BacktestConfig) -> tuple[pd.DataFrame, Dict[int, Dict]]:
    df = _read_csv(str(cfg.csv))
    df = df.sort_values("ts").reset_index(drop=True)
    df["ma_fast"] = df["price"].rolling(cfg.fast, min_periods=cfg.fast).mean()
    df["ma_slow"] = df["price"].rolling(cfg.slow, min_periods=cfg.slow).mean()

    feats = _rolling_features(df["price"].values, df["volume"].values, window=120)
    if len(feats) <= 120:
        raise SystemExit("Insufficient rows for HMM warmup (need > 120)")

    feats = feats.iloc[120:].reset_index(drop=True)
    df_trimmed = df.iloc[120:].reset_index(drop=True)

    with open(cfg.hmm, "rb") as f:
        model = pickle.load(f)

    X = feats.values
    probs = model.predict_proba(X)
    preds = (
        model.model.predict(model.scaler.transform(X))
        if hasattr(model, "model")
        else np.argmax(probs, axis=1)
    )

    df_trimmed["state"] = preds
    df_trimmed["p_bull"] = (
        probs[:, np.argmax(probs.mean(axis=0))] if probs.size else 0.5
    )

    df_trimmed["price"].pct_change().fillna(0)
    avg_ret = df_trimmed.groupby("state")["price"].pct_change().mean().fillna(0)
    order = np.argsort(avg_ret.values)
    state_to_regime: Dict[int, str] = {}
    if len(order) >= 1:
        state_to_regime[order[0]] = "bear"
        state_to_regime[order[-1]] = "bull"
    if len(order) >= 3:
        state_to_regime[order[1]] = "chop"

    df_trimmed["regime"] = df_trimmed["state"].map(state_to_regime)
    if len(order) > 1:
        df_trimmed["p_bull"] = probs[:, order[-1]]
        df_trimmed["p_bear"] = probs[:, order[0]]
    else:
        df_trimmed["p_bull"] = 0.5
        df_trimmed["p_bear"] = 0.5
    if len(order) > 2:
        df_trimmed["p_chop"] = probs[:, order[1]]
    else:
        df_trimmed["p_chop"] = 1.0 - df_trimmed["p_bull"] - df_trimmed["p_bear"]

    if df["ts"].max() > 1e12:
        df_trimmed["ts_ms"] = df_trimmed["ts"].astype(int)
    else:
        df_trimmed["ts_ms"] = (df_trimmed["ts"] * 1000.0).astype(int)

    metrics: Dict[int, Dict] = {}
    for row in df_trimmed.itertuples():
        metrics[int(row.ts_ms)] = {
            "price": float(row.price),
            "volume": float(row.volume),
            "ma_fast": float(row.ma_fast) if not math.isnan(row.ma_fast) else None,
            "ma_slow": float(row.ma_slow) if not math.isnan(row.ma_slow) else None,
            "regime": getattr(row, "regime", None),
            "p_bull": float(getattr(row, "p_bull", 0.5)),
            "p_bear": float(getattr(row, "p_bear", 0.5)),
        }

    return df_trimmed, metrics


class EnsembleSignalGenerator:
    def __init__(self, cfg: BacktestConfig, metrics: Dict[int, Dict]) -> None:
        self.cfg = cfg
        self.metrics = metrics

    def handle_tick(
        self, symbol: str, price: float, ts: float, volume: Optional[float] = None
    ) -> Optional[Dict]:
        ts_ms = int(round(ts * 1000.0))
        row = (
            self.metrics.get(ts_ms)
            or self.metrics.get(ts_ms - 1)
            or self.metrics.get(ts_ms + 1)
        )
        if not row:
            return None

        ma_fast = row.get("ma_fast")
        ma_slow = row.get("ma_slow")
        if ma_fast is None or ma_slow is None:
            return None

        ma_side = "BUY" if ma_fast > ma_slow else "SELL"
        try:
            ma_conf = min(1.0, abs((ma_fast - ma_slow) / price))
        except ZeroDivisionError:
            ma_conf = 0.0

        regime = row.get("regime")
        hmm_side = "BUY" if regime == "bull" else "SELL" if regime == "bear" else None
        hmm_conf = float(max(row.get("p_bull", 0.5), row.get("p_bear", 0.5)))

        score = 0.0
        score += self.cfg.w_ma * ma_conf * (1 if ma_side == "BUY" else -1)
        if hmm_side == "BUY":
            score += self.cfg.w_hmm * hmm_conf
        elif hmm_side == "SELL":
            score -= self.cfg.w_hmm * hmm_conf

        if abs(score) < self.cfg.min_conf:
            return None

        side = "BUY" if score > 0 else "SELL"
        return {
            "side": side,
            "score": score,
            "ma_side": ma_side,
            "ma_conf": ma_conf,
            "hmm_side": hmm_side,
            "hmm_conf": hmm_conf,
        }


def run_backtest(cfg: BacktestConfig, out_path: Path) -> Dict:
    df, metrics = _prepare_metrics(cfg)

    feed = FeedConfig(
        symbol=cfg.symbol.upper(),
        timeframe=cfg.timeframe,
        path=cfg.csv,
        driver=True,
        warmup_bars=cfg.warmup,
        timestamp_column="ts",
        price_column="price",
        volume_column="volume",
    )

    engine = BacktestEngine(
        feeds=[feed],
        strategy_factory=lambda client, clock: EnsembleSignalGenerator(cfg, metrics),
        patch_executor=True,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    balance = 0.0
    position = 0.0
    entry = 0.0
    last_trade_ts = 0.0
    wins = 0
    losses = 0
    equity_curve = []

    for step in engine.run():
        ts_sec = step.event.timestamp_seconds
        price = float(step.event.price)

        # Manage open position exits
        if position != 0:
            if position > 0:
                if price >= pct_to_price(entry, cfg.tp_bps):
                    pnl = (price - entry) * position
                    balance += pnl
                    position = 0
                    entry = 0
                    wins += 1
                elif price <= pct_to_price(entry, -cfg.sl_bps):
                    pnl = (price - entry) * position
                    balance += pnl
                    position = 0
                    entry = 0
                    losses += 1
            else:
                if price <= pct_to_price(entry, -cfg.tp_bps):
                    pnl = (entry - price) * abs(position)
                    balance += pnl
                    position = 0
                    entry = 0
                    wins += 1
                elif price >= pct_to_price(entry, cfg.sl_bps):
                    pnl = (entry - price) * abs(position)
                    balance += pnl
                    position = 0
                    entry = 0
                    losses += 1

        signal = step.response
        if not signal:
            equity_curve.append((ts_sec, balance + position * (price - entry)))
            continue

        if ts_sec - last_trade_ts < cfg.cooldown:
            equity_curve.append((ts_sec, balance + position * (price - entry)))
            continue

        side = signal.get("side")
        if not side or position != 0:
            equity_curve.append((ts_sec, balance + position * (price - entry)))
            continue

        slip_factor = cfg.slippage_bps / 10000.0
        if side == "BUY":
            entry = price * (1 + slip_factor)
            position = cfg.quote / entry
        else:
            entry = price * (1 - slip_factor)
            position = -cfg.quote / entry
        last_trade_ts = ts_sec

        equity_curve.append((ts_sec, balance + position * (price - entry)))

    eq_df = pd.DataFrame(equity_curve, columns=["ts", "equity_usd"])
    eq_df["date"] = pd.to_datetime(eq_df["ts"], unit="s")
    csv_out = out_path.with_suffix(".csv")
    eq_df.to_csv(csv_out, index=False)

    returns = eq_df["equity_usd"].diff().fillna(0)
    mean, std = returns.mean(), returns.std()
    sharpe = (mean / (std + 1e-9)) * math.sqrt(252 * 24 * 60) if std else 0.0
    drawdown = (eq_df["equity_usd"].cummax() - eq_df["equity_usd"]).max()

    orders = [asdict(order) for order in engine.recorded_orders]

    summary = dict(
        symbol=cfg.symbol,
        quote=cfg.quote,
        trades=wins + losses,
        wins=wins,
        losses=losses,
        winrate=(wins / (wins + losses)) if (wins + losses) > 0 else 0.0,
        pnl_usd=round(balance, 2),
        sharpe=round(float(sharpe), 3),
        max_drawdown_usd=round(float(drawdown), 2),
        final_equity_usd=round(balance, 2),
        config=dict(
            fast=cfg.fast,
            slow=cfg.slow,
            weights={"ma_v1": cfg.w_ma, "hmm_v1": cfg.w_hmm},
            min_conf=cfg.min_conf,
            tp_bps=cfg.tp_bps,
            sl_bps=cfg.sl_bps,
            cooldown=cfg.cooldown,
            slippage_bps=cfg.slippage_bps,
        ),
        orders_recorded=len(orders),
    )

    payload = {"summary": summary, "orders": orders}
    out_path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nEquity curve saved to: {csv_out}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest HMM+MA ensemble strategy")
    ap.add_argument(
        "--csv", required=True, help="Path to price CSV with ts,price,volume"
    )
    ap.add_argument("--hmm", required=True, help="Path to trained HMM model .pkl")
    ap.add_argument("--symbol", required=True, help="Trading symbol")
    ap.add_argument("--timeframe", default="1m", help="Label for the dataset timeframe")
    ap.add_argument("--quote", type=float, default=100, help="Quote amount per trade")
    ap.add_argument("--fast", type=int, default=9, help="Fast MA window")
    ap.add_argument("--slow", type=int, default=21, help="Slow MA window")
    ap.add_argument(
        "--tp-bps", type=float, default=20, help="Take profit in basis points"
    )
    ap.add_argument(
        "--sl-bps", type=float, default=30, help="Stop loss in basis points"
    )
    ap.add_argument(
        "--cooldown", type=int, default=30, help="Cooldown between trades (seconds)"
    )
    ap.add_argument(
        "--slippage-bps", type=float, default=3, help="Trading slippage in basis points"
    )
    ap.add_argument(
        "--min-conf", type=float, default=0.6, help="Minimum ensemble confidence"
    )
    ap.add_argument("--w-ma", type=float, default=0.4, help="Weight for MA signals")
    ap.add_argument("--w-hmm", type=float, default=0.6, help="Weight for HMM signals")
    ap.add_argument(
        "--out", default="reports/backtest_ensemble.json", help="Output JSON path"
    )

    args = ap.parse_args()

    cfg = BacktestConfig(
        csv=Path(args.csv),
        hmm=Path(args.hmm),
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        quote=args.quote,
        fast=args.fast,
        slow=args.slow,
        tp_bps=args.tp_bps,
        sl_bps=args.sl_bps,
        cooldown=float(args.cooldown),
        min_conf=args.min_conf,
        w_ma=args.w_ma,
        w_hmm=args.w_hmm,
        slippage_bps=args.slippage_bps,
    )

    run_backtest(cfg, Path(args.out))


if __name__ == "__main__":
    main()
