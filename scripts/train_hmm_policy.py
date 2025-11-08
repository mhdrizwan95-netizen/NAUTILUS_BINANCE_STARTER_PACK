#!/usr/bin/env python3
"""
Train an HMM regime model for the strategy brain.

Usage:
  python scripts/train_hmm_policy.py \
    --csv data/BTCUSDT_1m.csv \
    --symbol BTCUSDT \
    --window 120 \
    --states 3 \
    --out engine/models/hmm_policy.pkl

CSV columns required: ts, price, volume
ts can be epoch seconds or ms.
"""

import argparse
import os
import pickle
import warnings
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=RuntimeWarning)


@dataclass
class TrainConfig:
    csv: str
    symbol: str
    window: int
    states: int
    seed: int
    out: str
    min_rows: int
    cov: str
    stride: int


def _read_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    for k in ["ts", "price", "volume"]:
        if k not in cols:
            raise ValueError(f"CSV missing required column '{k}'")
    df = df.rename(columns={cols["ts"]: "ts", cols["price"]: "price", cols["volume"]: "volume"})
    # normalize ts to seconds
    if df["ts"].max() > 1e12:  # probably ms
        df["ts"] = (df["ts"] / 1000.0).astype(float)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def _rolling_features(price: np.ndarray, volume: np.ndarray, window: int) -> pd.DataFrame:
    # Simple 1-step returns
    rets = np.zeros_like(price)
    rets[1:] = (price[1:] - price[:-1]) / np.where(price[:-1] == 0, 1e-12, price[:-1])

    s = pd.DataFrame({"price": price, "volume": volume, "ret": rets})
    s["vola"] = s["ret"].rolling(20, min_periods=2).std().fillna(0.0)

    # VWAP deviation over 'window'
    vw_num = (s["price"] * s["volume"]).rolling(window, min_periods=1).sum()
    vw_den = (s["volume"]).rolling(window, min_periods=1).sum().replace(0, 1.0)
    vwap = vw_num / vw_den
    s["vwap_dev"] = (s["price"] - vwap) / vwap.replace(0, 1.0)

    # z-score of price over 30
    roll = s["price"].rolling(30, min_periods=2)
    mean30 = roll.mean()
    std30 = roll.std().replace(0, 1.0)
    s["zprice30"] = (s["price"] - mean30) / std30

    # volume spike ratio vs last 20
    vol_ma20 = s["volume"].rolling(20, min_periods=1).mean().replace(0, 1.0)
    s["vol_spike"] = s["volume"] / vol_ma20

    # latest return as in runtime features
    s["ret_last"] = s["ret"]

    feats = s[["ret_last", "vola", "vwap_dev", "zprice30", "vol_spike"]].copy()
    feats = feats.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return feats


def _train_val_split(X: np.ndarray, split_ratio: float = 0.8) -> Tuple[np.ndarray, np.ndarray]:
    n = len(X)
    ntr = max(10, int(n * split_ratio))
    return X[:ntr], X[ntr:]


class HMMPolicyWrapper:
    """
    Thin wrapper to match engine runtime contract:
      - exposes predict_proba(X) -> ndarray [n_samples, n_states]
    We also store the feature StandardScaler to match training-time normalization.
    """

    def __init__(self, model: GaussianHMM, scaler: StandardScaler):
        self.model = model
        self.scaler = scaler

    def predict_proba(self, X):
        X = np.asarray(X, dtype=float)
        Xs = self.scaler.transform(X)
        # hmmlearn provides predict_proba for posterior state probabilities via score_samples
        logprob, posteriors = self.model.score_samples(Xs)
        return posteriors


def main(cfg: TrainConfig):
    os.makedirs(os.path.dirname(cfg.out), exist_ok=True)
    df = _read_csv(cfg.csv)
    if len(df) < cfg.min_rows:
        raise SystemExit(f"Not enough rows in CSV ({len(df)} < {cfg.min_rows})")

    feats = _rolling_features(
        df["price"].values.astype(float), df["volume"].values.astype(float), cfg.window
    )

    # Drop warmup NaNs just in case
    feats = feats.iloc[cfg.window :].reset_index(drop=True)
    if len(feats) < cfg.min_rows:
        raise SystemExit("Not enough feature rows after window warmup.")

    # Normalize features
    scaler = StandardScaler()
    X = scaler.fit_transform(feats.values)

    # Train/val split (time-based)
    Xtr, Xval = _train_val_split(X, 0.85)

    # HMM fit
    hmm = GaussianHMM(
        n_components=cfg.states,
        covariance_type=cfg.cov,
        n_iter=200,
        random_state=cfg.seed,
        verbose=False,
    )
    hmm.fit(Xtr)

    # Evaluate log likelihood on train/val
    ll_tr = hmm.score(Xtr) if len(Xtr) else float("nan")
    ll_va = hmm.score(Xval) if len(Xval) else float("nan") if len(Xval) else float("nan")

    # Persist wrapper
    wrapper = HMMPolicyWrapper(hmm, scaler)
    with open(cfg.out, "wb") as f:
        pickle.dump(wrapper, f)

    print(
        {
            "model": "GaussianHMM",
            "states": cfg.states,
            "cov": cfg.cov,
            "window": cfg.window,
            "rows_train": int(len(Xtr)),
            "rows_val": int(len(Xval)),
            "loglike_train": float(ll_tr),
            "loglike_val": float(ll_va),
            "out": cfg.out,
        }
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to price CSV with ts,price,volume")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--window", type=int, default=120, help="rolling window for vwap/zscore")
    ap.add_argument("--states", type=int, default=3, help="number of regimes")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cov", default="diag", choices=["diag", "full", "spherical", "tied"])
    ap.add_argument("--min-rows", type=int, default=2000)
    ap.add_argument("--stride", type=int, default=1, help="reserved: future sub-sampling")
    ap.add_argument("--out", default="engine/models/hmm_policy.pkl")
    args = ap.parse_args()
    cfg = TrainConfig(
        csv=args.csv,
        symbol=args.symbol,
        window=args.window,
        states=args.states,
        seed=args.seed,
        out=args.out,
        min_rows=args.min_rows,
        cov=args.cov,
        stride=args.stride,
    )
    main(cfg)
