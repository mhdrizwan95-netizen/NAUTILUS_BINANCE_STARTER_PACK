import json
import os
from typing import Optional, Dict, Any

import numpy as np
import pandas as pd


MODEL_PATH = os.getenv("SLIP_MODEL_PATH", "data/slip_model.json")
PARQUET_PATH = os.getenv("SLIP_TRAIN_PATH", "data/fills.parquet")

FEATURES = [
    "spread_bp",
    "depth_imbalance",
    "depth_usd",
    "atrp_1m",
    "order_quote_usd",
    "is_burst",
    "side",
]


def fit_ridge(X: np.ndarray, y: np.ndarray, lam: float = 1.0) -> np.ndarray:
    XtX = X.T @ X
    XtX += lam * np.eye(X.shape[1])
    w = np.linalg.solve(XtX, X.T @ y)
    return w


def train_from_parquet(parq_path: str = PARQUET_PATH, lam: float = 1.0, min_rows: int = 200) -> Optional[Dict[str, Any]]:
    if not os.path.exists(parq_path):
        return None
    df = pd.read_parquet(parq_path)
    cols = [c for c in FEATURES if c in df.columns]
    if "slip_bp" not in df.columns or len(cols) != len(FEATURES):
        return None
    df = df.dropna(subset=["slip_bp"] + FEATURES)
    if len(df) < min_rows:
        return None
    X = df[FEATURES].astype(float).values
    mu = X.mean(axis=0)
    sigma = X.std(axis=0) + 1e-9
    Xz = (X - mu) / sigma
    y = df["slip_bp"].astype(float).values
    w = fit_ridge(Xz, y, lam=lam)
    model = {"w": w.tolist(), "mu": mu.tolist(), "sigma": sigma.tolist(), "features": FEATURES}
    os.makedirs(os.path.dirname(MODEL_PATH) or ".", exist_ok=True)
    with open(MODEL_PATH, "w") as f:
        json.dump(model, f)
    return model


def load_model() -> Optional[Dict[str, Any]]:
    if not os.path.exists(MODEL_PATH):
        return None
    with open(MODEL_PATH) as f:
        return json.load(f)


def predict_slip_bp(model: Dict[str, Any], feat_row: Dict[str, float]) -> float:
    x = np.array([float(feat_row[k]) for k in model["features"]], dtype=float)
    mu = np.array(model["mu"], dtype=float)
    sigma = np.array(model["sigma"], dtype=float)
    w = np.array(model["w"], dtype=float)
    xz = (x - mu) / sigma
    return float(w.dot(xz))


def append_row_to_parquet(row: Dict[str, Any], parq_path: str = PARQUET_PATH) -> None:
    """Append a single row dict to a Parquet file (overwrite small file approach)."""
    try:
        os.makedirs(os.path.dirname(parq_path) or ".", exist_ok=True)
        if os.path.exists(parq_path):
            df = pd.read_parquet(parq_path)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_parquet(parq_path, index=False)
    except Exception:
        # Best-effort logging only
        pass

