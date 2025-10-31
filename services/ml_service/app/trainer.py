
from pathlib import Path
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from loguru import logger
from .config import settings
from . import model_store
from common import manifest

def _load_new_data() -> pd.DataFrame:
    """
    Build a dataframe from files claimed from the ledger.
    If EXACTLY_ONCE is True, we only use newly downloaded bars once.
    If False, we will construct a sliding window (last TRAIN_WINDOW_DAYS) from all available bars.
    """
    # Claim some files to work on
    claimed = manifest.claim_unprocessed(limit=1000, db_path=settings.LEDGER_DB)
    if not claimed and settings.EXACTLY_ONCE:
        # nothing new
        return pd.DataFrame(columns=["timestamp","close"])

    dfs = []
    # parse CSVs for claimed files
    for row in claimed:
        path = row["path"]
        try:
            df = pd.read_csv(path)
            if "timestamp" not in df.columns:
                # assume first col
                df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
            dfs.append(df[["timestamp","close"]])
        except Exception as e:
            logger.warning(f"skipping {path}: {e}")
    if not dfs:
        # Fallback: sliding window from disk (non-strict mode)
        if not settings.EXACTLY_ONCE:
            return _load_window_from_disk(days=settings.TRAIN_WINDOW_DAYS)
        return pd.DataFrame(columns=["timestamp","close"])

    df = pd.concat(dfs, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")
    df.dropna(inplace=True)
    df.sort_values("timestamp", inplace=True)
    df.set_index("timestamp", inplace=True, drop=False)
    return df

def _load_window_from_disk(days: int) -> pd.DataFrame:
    root = Path(settings.DATA_DIR)
    files = sorted(list(root.glob("incoming/**/*.*")))
    dfs = []
    for p in files[-200:]:  # limit to last N files for speed
        try:
            df = pd.read_csv(p)
            if "timestamp" not in df.columns:
                df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
            dfs.append(df[["timestamp","close"]])
        except Exception:
            pass
    if not dfs:
        return pd.DataFrame(columns=["timestamp","close"])
    df = pd.concat(dfs, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")
    df.dropna(inplace=True)
    df.sort_values("timestamp", inplace=True)
    cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
    df = df[df["timestamp"] >= cutoff]
    df.set_index("timestamp", inplace=True, drop=False)
    return df

def _train_hmm(X: np.ndarray, n_states: int) -> Tuple[GaussianHMM, StandardScaler, Dict[str, Any]]:
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    n = len(Xs)
    if n < 100:
        raise RuntimeError("not enough points to train")
    split = int(n*0.8)
    Xtr, Xval = Xs[:split], Xs[split:]
    hmm = GaussianHMM(n_components=n_states, covariance_type="full", n_iter=200, random_state=42)
    hmm.fit(Xtr)
    val_ll = float(hmm.score(Xval) / max(len(Xval),1))
    meta = {"metric_name":"val_log_likelihood","metric_value":val_ll,"n_obs":n,"n_states":n_states}
    return hmm, scaler, meta

def _mark_claimed_as_processed(delete_after: bool = True):
    # For simplicity, mark *all* currently 'processing' as processed/deleted.
    rows = manifest.claim_unprocessed(limit=0, db_path=settings.LEDGER_DB)  # no-op claim
    # nothing to do; we need to flip those we actually used; 
    # Instead, rely on status transition when claiming; we will read processing from DB.
    import sqlite3
    conn = sqlite3.connect(settings.LEDGER_DB, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT file_id FROM files WHERE status='processing'")
    ids = [r[0] for r in cur.fetchall()]
    conn.close()
    for fid in ids:
        manifest.mark_processed(fid, delete_file=delete_after, db_path=settings.LEDGER_DB)

def train_once(n_states: int = None, tag: str = None, promote: bool = True) -> Dict[str, Any]:
    n_states = n_states or settings.HMM_STATES
    df = _load_new_data()
    if df.empty:
        return {"message": "no new data", "promoted": False, "metadata": {"n_obs": 0}}
    df["logret"] = np.log(df["close"]).diff()
    df.dropna(inplace=True)
    if len(df) < settings.TRAIN_MIN_POINTS:
        return {"message": "not enough new data", "promoted": False, "metadata": {"n_obs": int(len(df))}}
    X = df[["logret"]].values.astype(np.float64)
    hmm, scaler, meta = _train_hmm(X, n_states=n_states)
    
    version_dir = model_store.save_version(hmm, scaler, metadata={**meta, "tag": tag})
    meta = {**meta, "version_id": version_dir.name}

    promoted = False
    if promote and settings.AUTO_PROMOTE:
        cur_model, cur_scaler, cur_meta = model_store.load_current()
        cur_val = cur_meta.get("metric_value", float("-inf")) if cur_meta else float("-inf")
        if (meta["metric_value"] - cur_val) >= settings.PROMOTION_MIN_DELTA:
            model_store.promote(version_dir)
            promoted = True
            model_store.prune_keep_last(settings.KEEP_N_MODELS)
    # Mark claimed files as processed and delete if configured
    _mark_claimed_as_processed(delete_after=settings.DELETE_AFTER_PROCESS)

    return {"version_dir": str(version_dir), "metadata": meta, "promoted": promoted}
