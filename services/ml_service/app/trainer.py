import os
from pathlib import Path
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from loguru import logger
from .config import settings
from . import model_store


def _load_data() -> pd.DataFrame:
    data_root = Path(settings.DATA_DIR)
    # naive: read all CSVs and concat by time (expects columns at least: timestamp, close)
    dfs = []
    for csv in sorted(data_root.glob(settings.TRAIN_DATA_GLOB)):
        try:
            df = pd.read_csv(csv)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Skipping {csv}: {e}")
    if not dfs:
        raise RuntimeError(f"No data found in {data_root} (glob={settings.TRAIN_DATA_GLOB})")
    df = pd.concat(dfs, ignore_index=True)
    # normalize schema
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values("timestamp", inplace=True)
        df.set_index("timestamp", inplace=True, drop=False)
    # minimal feature set: log returns
    close_col = "close" if "close" in df.columns else df.columns[-1]
    df["logret"] = np.log(df[close_col]).diff()
    df.dropna(inplace=True)
    # restrict to recent window
    if settings.TRAIN_WINDOW_DAYS and "timestamp" in df.columns:
        cutoff = df["timestamp"].max() - pd.Timedelta(days=settings.TRAIN_WINDOW_DAYS)
        df = df[df["timestamp"] >= cutoff]
    return df[["logret"]]


def _train_hmm(X: np.ndarray, n_states: int) -> Tuple[GaussianHMM, StandardScaler, Dict[str, Any]]:
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    # Train/valid split
    n = len(Xs)
    split = int(n * 0.8)
    Xtr, Xval = Xs[:split], Xs[split:]
    hmm = GaussianHMM(n_components=n_states, covariance_type="full", n_iter=200, random_state=42)
    hmm.fit(Xtr)
    # Validation metric: per-sample log-likelihood
    val_ll = float(hmm.score(Xval) / max(len(Xval), 1))
    meta = {
        "metric_name": "val_log_likelihood",
        "metric_value": val_ll,
        "n_obs": n,
        "n_states": n_states,
    }
    return hmm, scaler, meta


def train_once(n_states: int = None, tag: str = None, promote: bool = True) -> Dict[str, Any]:
    n_states = n_states or settings.HMM_STATES
    df = _load_data()
    X = df.values.astype(np.float64)
    hmm, scaler, meta = _train_hmm(X, n_states=n_states)
    # Save version
    version_dir = model_store.save_version(hmm, scaler, metadata={**meta, "tag": tag})
    # Decide promotion
    promoted = False
    if promote and settings.AUTO_PROMOTE:
        cur_model, cur_scaler, cur_meta = model_store.load_current()
        cur_val = cur_meta.get("metric_value", float("-inf")) if cur_meta else float("-inf")
        new_val = meta["metric_value"]
        if (new_val - cur_val) >= settings.PROMOTION_MIN_DELTA:
            model_store.promote(version_dir)
            promoted = True
            model_store.prune_keep_last(settings.KEEP_N_MODELS)
            logger.info(f"Promoted new model (Δ={new_val - cur_val:.3f})")
        else:
            logger.info(f"Held back new model (Δ={new_val - cur_val:.3f})")
    return {
        "version_dir": str(version_dir),
        "metadata": meta,
        "promoted": promoted,
    }
