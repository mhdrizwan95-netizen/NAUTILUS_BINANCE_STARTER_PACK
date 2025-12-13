"""HMM model training for the ML service."""

import logging
import os
from typing import Any

import numpy as np

from . import model_store

logger = logging.getLogger(__name__)


def train_once(
    n_states: int = 3,
    tag: str = "v1",
    promote: bool = True,
) -> dict[str, Any]:
    """Train an HMM model on available data.
    
    Args:
        n_states: Number of hidden states (default 3: BULL, BEAR, CHOP)
        tag: Version tag for the model
        promote: Whether to promote to active after training
        
    Returns:
        Training result with version_dir, metadata, promoted status
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        logger.warning("hmmlearn not available, creating mock model")
        return _create_mock_model(n_states, tag, promote)
    
    # Try to load training data
    data = _load_training_data()
    
    if data is None or len(data) < 100:
        logger.warning("Insufficient training data, creating default model")
        return _create_default_model(n_states, tag, promote)
    
    try:
        # Train HMM
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=100,
            random_state=42,
        )
        
        # Reshape data for HMM (samples, features)
        X = data.reshape(-1, 1) if data.ndim == 1 else data
        model.fit(X)
        
        # Compute metrics
        log_likelihood = model.score(X)
        
        metadata = {
            "n_states": n_states,
            "n_samples": len(X),
            "log_likelihood": float(log_likelihood),
            "metric_name": "val_log_likelihood",
            "metric_value": float(log_likelihood),
        }
        
        # Save model
        version_dir = model_store.save_model(
            model=model,
            scaler=None,
            metadata=metadata,
            tag=tag,
            promote=promote,
        )
        
        return {
            "version_dir": version_dir,
            "metadata": metadata,
            "promoted": promote,
            "message": f"Trained HMM with {n_states} states on {len(X)} samples",
        }
        
    except Exception as e:
        logger.exception("HMM training failed")
        return {
            "version_dir": "",
            "metadata": {"error": str(e)},
            "promoted": False,
            "message": f"Training failed: {e}",
        }


def _load_training_data() -> np.ndarray | None:
    """Load training data from the data directory."""
    data_dir = os.getenv("ML_DATA_DIR", "/ml/data")
    
    # Try to load incoming data files
    try:
        import glob
        
        files = glob.glob(f"{data_dir}/**/*.csv", recursive=True)
        if not files:
            return None
        
        import pandas as pd
        
        dfs = []
        for f in files[:10]:  # Limit to 10 files
            try:
                df = pd.read_csv(f)
                if "close" in df.columns:
                    # Align with engine/strategies/policy_hmm.py features
                    # 1. Log Returns
                    df["ret"] = np.log(df["close"] / df["close"].shift(1))
                    
                    # 2. Volatility (20)
                    df["vol"] = df["ret"].rolling(20).std()
                    
                    # 3. VWAP Deviation
                    if "volume" in df.columns:
                        vwap = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
                        df["dev_vwap"] = (df["close"] - vwap) / vwap
                        
                        # 5. Volume Spike (20) - (Index 5 in list, but we compute parallel)
                        vol_safe = df["volume"].replace(0, 1) # avoid div by zero
                        df["vol_spike"] = df["volume"] / vol_safe.rolling(20).mean()
                    else:
                        df["dev_vwap"] = 0.0
                        df["vol_spike"] = 1.0

                    # 4. Z-Score (30)
                    r30_mean = df["close"].rolling(30).mean()
                    r30_std = df["close"].rolling(30).std()
                    df["zscore"] = (df["close"] - r30_mean) / r30_std

                    # Drop NaN from rolling windows
                    df_clean = df[["ret", "vol", "dev_vwap", "zscore", "vol_spike"]].dropna()
                    
                    if not df_clean.empty:
                        dfs.append(df_clean.values)
            except Exception:
                continue
        
        if dfs:
            return np.concatenate(dfs, axis=0)
        return None
        
    except Exception:
        return None


def _create_default_model(n_states: int, tag: str, promote: bool) -> dict[str, Any]:
    """Create a default/untrained model for bootstrap purposes."""
    try:
        from hmmlearn.hmm import GaussianHMM
        
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=10,
            random_state=42,
        )
        
        # Fit on synthetic data to initialize (5 features: ret, vol, dev_vwap, zscore, vol_spike)
        synthetic = np.random.randn(1000, 5)
        # Scale to look realistic
        synthetic[:, 0] *= 0.01  # Ret
        synthetic[:, 1] *= 0.02  # Vol
        synthetic[:, 2] *= 0.05  # Dev
        synthetic[:, 3] *= 1.0   # Zscore
        synthetic[:, 4] *= 1.0   # Spike
        model.fit(synthetic)
        
        metadata = {
            "n_states": n_states,
            "n_samples": 1000,
            "log_likelihood": float(model.score(synthetic)),
            "metric_name": "val_log_likelihood",
            "metric_value": float(model.score(synthetic)),
            "synthetic": True,
        }
        
        version_dir = model_store.save_model(
            model=model,
            scaler=None,
            metadata=metadata,
            tag=tag,
            promote=promote,
        )
        
        return {
            "version_dir": version_dir,
            "metadata": metadata,
            "promoted": promote,
            "message": "Created default model (no training data available)",
        }
        
    except ImportError:
        return _create_mock_model(n_states, tag, promote)


def _create_mock_model(n_states: int, tag: str, promote: bool) -> dict[str, Any]:
    """Create a mock model when hmmlearn is not available."""
    
    class MockHMM:
        """Mock HMM for environments without hmmlearn."""
        
        def __init__(self, n_components: int):
            self.n_components = n_components
        
        def predict_proba(self, X) -> np.ndarray:
            """Return uniform probabilities."""
            n_samples = len(X) if hasattr(X, "__len__") else 1
            return np.ones((n_samples, self.n_components)) / self.n_components
        
        def predict(self, X) -> np.ndarray:
            """Return neutral state."""
            n_samples = len(X) if hasattr(X, "__len__") else 1
            return np.zeros(n_samples, dtype=int)
    
    model = MockHMM(n_states)
    
    metadata = {
        "n_states": n_states,
        "n_samples": 0,
        "log_likelihood": 0.0,
        "metric_name": "val_log_likelihood",
        "metric_value": 0.0,
        "mock": True,
    }
    
    version_dir = model_store.save_model(
        model=model,
        scaler=None,
        metadata=metadata,
        tag=tag,
        promote=promote,
    )
    
    return {
        "version_dir": version_dir,
        "metadata": metadata,
        "promoted": promote,
        "message": "Created mock model (hmmlearn not installed)",
    }
