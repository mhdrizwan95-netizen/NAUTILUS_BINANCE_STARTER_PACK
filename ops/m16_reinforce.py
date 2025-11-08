#!/usr/bin/env python3
import json
import os
import pickle
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sklearn.linear_model import SGDClassifier

OUT_DIR = os.path.join("data", "processed", "m16")
CAL_DIR = os.path.join("data", "processed", "calibration")
MODEL_DIR = os.path.join("ml_service", "model_store")
os.makedirs(OUT_DIR, exist_ok=True)

FEEDBACK = os.path.join("data", "processed", "feedback_log.csv")
POLICY_PATH = os.path.join(MODEL_DIR, "policy_vNext.joblib")  # overwrite candidate
POLICY_FALLBACK = os.path.join(MODEL_DIR, "policy_v1.joblib")  # in case

# Hyperparameters (can be moved to YAML)
GAMMA = float(os.environ.get("M16_GAMMA", "0.997"))  # recency decay per row
ALPHA = float(os.environ.get("M16_ALPHA", "1.0"))  # confidence exponent
LAMBDA = float(os.environ.get("M16_LAMBDA", "0.15"))  # state DD penalty
MU = float(os.environ.get("M16_MU", "0.03"))  # spread penalty
LR = float(os.environ.get("M16_LR", "0.01"))  # SGD step size
KL_MAX = float(os.environ.get("M16_KL_MAX", "0.03"))  # trust region


def robust_reward(pnl: pd.Series) -> pd.Series:
    return np.sign(pnl) * np.log1p(np.abs(pnl))


def load_feedback(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # expected columns: ts, state, action, confidence, pnl, (optional) spread_bp, drawdown_state, act_prob
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.sort_values("ts")
    for col in ["state", "action", "confidence", "pnl"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    # add safe defaults
    for c, val in [("spread_bp", 5.0), ("drawdown_state", 0.0), ("act_prob", np.nan)]:
        if c not in df.columns:
            df[c] = val
    return df


def weights(df: pd.DataFrame) -> np.ndarray:
    n = len(df)
    recency = np.power(GAMMA, np.arange(n, 0, -1))  # newest highest weight
    conf = np.clip(df["confidence"].values, 1e-3, 1.0) ** ALPHA
    risk_pen = (
        1.0
        + LAMBDA * np.clip(df["drawdown_state"].values, 0, None)
        + MU * np.clip(df["spread_bp"].values, 0, None)
    )
    w = recency * conf / np.clip(risk_pen, 1e-3, None)
    return w / (w.mean() + 1e-9)


def ips_correction(df: pd.DataFrame, p_hat: np.ndarray) -> np.ndarray:
    """Inverse propensity score weights; fall back to proxy probs if act_prob NA."""
    act = df["action"].values
    logged = df["act_prob"].values
    # Map actions {-1,0,1} to index {0,1,2}
    a_idx = (act + 1).astype(int)
    # p_hat shape (N,3)
    probs = p_hat[np.arange(len(df)), a_idx]
    denom = np.where(np.isnan(logged) | (logged <= 0) | (logged > 1), probs, logged)
    return np.clip(1.0 / np.clip(denom, 1e-3, 1.0), 0, 50.0)


def kl_divergence(p_old: np.ndarray, p_new: np.ndarray) -> float:
    eps = 1e-8
    p_old = np.clip(p_old, eps, 1.0)
    p_new = np.clip(p_new, eps, 1.0)
    return float(np.mean(np.sum(p_old * (np.log(p_old) - np.log(p_new)), axis=1)))


def features(df: pd.DataFrame) -> np.ndarray:
    # One-hot states + confidence as continuous + bias.
    states = sorted(df["state"].astype(int).unique().tolist())
    s_map = {s: i for i, s in enumerate(states)}
    S = np.zeros((len(df), len(states)))
    for i, s in enumerate(df["state"].astype(int).values):
        S[i, s_map[s]] = 1.0
    conf = df["confidence"].values.reshape(-1, 1)
    X = np.hstack([S, conf])
    return X, states


def train_proxy_probe(df: pd.DataFrame, X: np.ndarray) -> Tuple[np.ndarray, SGDClassifier]:
    # 3-class (short/hold/long) with probability outputs (softmax via log_loss)
    y = (df["action"].astype(int) + 1).values  # {-1,0,1} -> {0,1,2}
    clf = SGDClassifier(loss="log_loss", learning_rate="constant", eta0=LR, max_iter=2000)
    clf.fit(X, y)
    # probs for IPS fallback
    # For SGDClassifier, decision_function -> softmax manually:
    logits = clf.decision_function(X)
    if logits.ndim == 1:  # degenerate
        logits = np.stack([-logits, np.zeros_like(logits), logits], axis=1)
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = e / e.sum(axis=1, keepdims=True)
    return probs, clf


def guarded_update(df: pd.DataFrame) -> Dict:
    if len(df) < 200:
        return {"status": "skipped", "reason": "not_enough_data", "n": len(df)}

    # Prepare features & rewards
    X, states = features(df)
    r = robust_reward(df["pnl"])
    base_w = weights(df)

    # Train proxy probe to get fallback action probs
    p_hat, probe = train_proxy_probe(df, X)

    # IPS correction
    ips = ips_correction(df, p_hat)
    w = base_w * ips

    # Policy: we reuse a simple multinomial logistic (SGD) over actions with sample weights
    y = (df["action"].astype(int) + 1).values
    policy = SGDClassifier(
        loss="log_loss", learning_rate="constant", eta0=LR, max_iter=1, warm_start=True
    )

    # Initialize with probe (same features) to avoid cold-start jumps
    policy.coef_ = getattr(probe, "coef_", None)
    policy.intercept_ = getattr(probe, "intercept_", None)
    policy.classes_ = np.array([0, 1, 2])

    # Old distribution for trust region
    logits_old = probe.decision_function(X)
    e_old = np.exp(logits_old - logits_old.max(axis=1, keepdims=True))
    p_old = e_old / e_old.sum(axis=1, keepdims=True)

    # One epoch weighted by reward
    sample_w = np.clip(np.array(w) * (r.values - r.mean()), -5, 5) + 1.0
    policy.partial_fit(X, y, classes=np.array([0, 1, 2]), sample_weight=sample_w)

    # Trust region: compute KL; if exceeded, interpolate toward old
    logits_new = policy.decision_function(X)
    e_new = np.exp(logits_new - logits_new.max(axis=1, keepdims=True))
    p_new = e_new / e_new.sum(axis=1, keepdims=True)
    kl = kl_divergence(p_old, p_new)
    if kl > KL_MAX:
        tau = KL_MAX / max(kl, 1e-6)
        p_blend = tau * p_new + (1 - tau) * p_old
        # Back out logits via log(p) (up to constant); refit a small ridge projection
        # For simplicity, regress class by class to approximate logits:
        Y = np.argmax(p_blend, axis=1)
        policy = SGDClassifier(
            loss="log_loss",
            learning_rate="constant",
            eta0=LR * tau,
            max_iter=200,
            alpha=1e-3,
        )
        policy.fit(X, Y)

    # Save candidate policy
    try:
        import joblib

        joblib.dump(policy, POLICY_PATH)
    except Exception:
        with open(POLICY_PATH + ".pkl", "wb") as f:
            pickle.dump(policy, f)

    # Metrics
    winrate = float((df[df["action"] != 0]["pnl"] > 0).mean()) if (df["action"] != 0).any() else 0.0
    avg_reward = float((r * base_w).mean())
    entropy = float((-(p_new * np.log(p_new + 1e-8)).sum(axis=1).mean()))

    # Learning curve
    import matplotlib.pyplot as plt

    lc_path = os.path.join(OUT_DIR, "learning_curve.png")
    rw = (r * base_w).rolling(200, min_periods=25).mean()
    plt.figure(figsize=(8, 3))
    plt.plot(rw.values)
    plt.title("M16 Learning Curve (γ-weighted reward)")
    plt.ylabel("reward")
    plt.xlabel("t")
    plt.tight_layout()
    plt.savefig(lc_path, dpi=160)
    plt.close()

    # Drift vs reward (if drift_score available elsewhere, we fallback to 0)
    drift = df.get("drift_score", pd.Series([0] * len(df)))
    dvr_path = os.path.join(OUT_DIR, "drift_vs_reward.png")
    plt.figure(figsize=(5, 4))
    plt.scatter(drift.values, r.values, s=6, alpha=0.3)
    plt.xlabel("drift_score")
    plt.ylabel("robust_reward")
    plt.title("Drift vs Reward")
    plt.tight_layout()
    plt.savefig(dvr_path, dpi=160)
    plt.close()

    # Prometheus exposition to file
    reg = CollectorRegistry()
    g1 = Gauge("m16_avg_reward", "avg recency-weighted reward", registry=reg)
    g1.set(avg_reward)
    g2 = Gauge("m16_entropy", "policy average entropy", registry=reg)
    g2.set(entropy)
    g3 = Gauge("m16_winrate", "trade win rate", registry=reg)
    g3.set(winrate)
    metrics_path = os.path.join(OUT_DIR, "metrics.prom")
    with open(metrics_path, "wb") as f:
        f.write(generate_latest(reg))

    return {
        "status": "ok",
        "n": int(len(df)),
        "avg_reward": avg_reward,
        "winrate": winrate,
        "entropy": entropy,
        "kl": kl,
        "paths": {
            "policy": POLICY_PATH,
            "learning_curve": lc_path,
            "drift_vs_reward": dvr_path,
            "metrics": metrics_path,
        },
    }


if __name__ == "__main__":
    if not os.path.exists(FEEDBACK):
        print("ERROR: feedback_log.csv missing.")
        raise SystemExit(2)
    df = load_feedback(FEEDBACK)
    res = guarded_update(df)
    print(json.dumps(res, indent=2))
