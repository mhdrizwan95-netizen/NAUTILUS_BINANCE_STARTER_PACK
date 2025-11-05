from pathlib import Path
from typing import Dict, Any, Tuple, List
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from loguru import logger
from .config import settings
from . import model_store
from common import manifest


def _load_new_data() -> Tuple[pd.DataFrame, List[str]]:
    """
    Build a dataframe from files claimed from the ledger.
    If EXACTLY_ONCE is True, we only use newly downloaded bars once.
    If False, we will construct a sliding window (last TRAIN_WINDOW_DAYS) from all available bars.
    """
    # Claim some files to work on
    claimed = manifest.claim_unprocessed(limit=1000, db_path=settings.LEDGER_DB)
    claimed_ids = [row.get("file_id") for row in claimed if row.get("file_id")]
    if not claimed and settings.EXACTLY_ONCE:
        # nothing new
        return pd.DataFrame(columns=["timestamp", "close"]), []

    dfs = []
    # parse CSVs for claimed files
    for row in claimed:
        path = row["path"]
        try:
            df = pd.read_csv(path)
            if "timestamp" not in df.columns:
                # assume first col
                df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
            dfs.append(df[["timestamp", "close"]])
        except Exception as e:
            logger.warning(f"skipping {path}: {e}")
    if not dfs:
        # Requeue anything we claimed before falling back
        if claimed_ids:
            _requeue_claims(claimed_ids)
        # Fallback: sliding window from disk (non-strict mode)
        if not settings.EXACTLY_ONCE:
            return _load_window_from_disk(days=settings.TRAIN_WINDOW_DAYS), []
        return pd.DataFrame(columns=["timestamp", "close"]), []

    df = pd.concat(dfs, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")
    df.dropna(inplace=True)
    df.sort_values("timestamp", inplace=True)
    df.set_index("timestamp", inplace=True, drop=False)
    return df, claimed_ids


def _load_window_from_disk(days: int) -> pd.DataFrame:
    root = Path(settings.DATA_DIR)
    files = sorted(list(root.glob("incoming/**/*.*")))
    dfs = []
    for p in files[-200:]:  # limit to last N files for speed
        try:
            df = pd.read_csv(p)
            if "timestamp" not in df.columns:
                df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
            dfs.append(df[["timestamp", "close"]])
        except Exception:
            pass
    if not dfs:
        return pd.DataFrame(columns=["timestamp", "close"])
    df = pd.concat(dfs, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")
    df.dropna(inplace=True)
    df.sort_values("timestamp", inplace=True)
    cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
    df = df[df["timestamp"] >= cutoff]
    df.set_index("timestamp", inplace=True, drop=False)
    return df


def _train_hmm(
    X: np.ndarray, n_states: int, seed: int
) -> Tuple[GaussianHMM, StandardScaler, Dict[str, Any]]:
    """Train HMM with time-aware split and no leakage.

    - Split first (80/20 in order) to respect temporal ordering.
    - Fit scaler on training only; transform both train/val with same scaler.
    """
    n = len(X)
    if n < 100:
        raise RuntimeError("not enough points to train")
    split = int(n * 0.8)
    Xtr_raw, Xval_raw = X[:split], X[split:]
    scaler = StandardScaler()
    Xtr = scaler.fit_transform(Xtr_raw)
    Xval = scaler.transform(Xval_raw)
    hmm = GaussianHMM(
        n_components=n_states, covariance_type="full", n_iter=200, random_state=seed
    )
    hmm.fit(Xtr)
    val_ll = float(hmm.score(Xval) / max(len(Xval), 1))
    meta = {
        "metric_name": "val_log_likelihood",
        "metric_value": val_ll,
        "n_obs": n,
        "n_states": n_states,
    }
    return hmm, scaler, meta


def _mark_claimed_as_processed(file_ids: List[str], delete_after: bool = True):
    if not file_ids:
        return
    for fid in file_ids:
        try:
            manifest.mark_processed(
                fid, delete_file=delete_after, db_path=settings.LEDGER_DB
            )
        except Exception as exc:
            logger.warning(f"failed to mark {fid} processed: {exc}")


def _requeue_claims(file_ids: List[str]):
    if not file_ids:
        return
    try:
        manifest.requeue(file_ids, db_path=settings.LEDGER_DB)
    except Exception as exc:
        logger.warning(f"failed to requeue {len(file_ids)} files: {exc}")


def train_once(
    n_states: int = None, tag: str = None, promote: bool = True
) -> Dict[str, Any]:
    n_states = n_states or settings.HMM_STATES
    np.random.seed(settings.TRAIN_SEED)
    df_new, claimed_ids = _load_new_data()

    if df_new.empty and not claimed_ids:
        if settings.EXACTLY_ONCE:
            return {
                "message": "no new data",
                "promoted": False,
                "metadata": {"n_obs": 0},
            }
        df = _load_window_from_disk(days=settings.TRAIN_WINDOW_DAYS)
    else:
        df = df_new.copy()
        if not settings.EXACTLY_ONCE:
            window_df = _load_window_from_disk(days=settings.TRAIN_WINDOW_DAYS)
            if not window_df.empty:
                df = pd.concat([window_df, df])
                df.sort_index(inplace=True)
                df = df[~df.index.duplicated(keep="last")]

    if df.empty:
        _requeue_claims(claimed_ids)
        return {
            "message": "no data available",
            "promoted": False,
            "metadata": {"n_obs": 0},
        }

    df["logret"] = np.log(df["close"]).diff()
    df.dropna(inplace=True)
    if len(df) < settings.TRAIN_MIN_POINTS:
        _requeue_claims(claimed_ids)
        return {
            "message": "not enough new data",
            "promoted": False,
            "metadata": {"n_obs": int(len(df))},
        }

    try:
        X = df[["logret"]].values.astype(np.float64)
        hmm, scaler, meta = _train_hmm(X, n_states=n_states, seed=settings.TRAIN_SEED)

        metadata_payload = {
            **meta,
            "tag": tag,
            "train_seed": settings.TRAIN_SEED,
        }
        version_dir = model_store.save_version(
            hmm,
            scaler,
            metadata=metadata_payload,
        )
        meta = {**metadata_payload, "version_id": version_dir.name}

        promoted = False
        if promote and settings.AUTO_PROMOTE:
            cur_model, cur_scaler, cur_meta = model_store.load_current()
            cur_val = (
                cur_meta.get("metric_value", float("-inf"))
                if cur_meta
                else float("-inf")
            )
            if (meta["metric_value"] - cur_val) >= settings.PROMOTION_MIN_DELTA:
                model_store.promote(version_dir)
                promoted = True
                model_store.prune_keep_last(settings.KEEP_N_MODELS)

        claimed_count = len(claimed_ids)
        _mark_claimed_as_processed(
            claimed_ids, delete_after=settings.DELETE_AFTER_PROCESS
        )
        claimed_ids = []
    except Exception:
        _requeue_claims(claimed_ids)
        raise

    meta = {**meta, "claimed_files": claimed_count}
    return {"version_dir": str(version_dir), "metadata": meta, "promoted": promoted}
