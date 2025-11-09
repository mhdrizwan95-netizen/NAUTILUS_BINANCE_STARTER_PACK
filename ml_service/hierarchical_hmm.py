#!/usr/bin/env python3
"""
ml_service/hierarchical_hmm.py — M17: Hierarchical HMM Regime System

Implements two-level Hidden Markov Model architecture:
1. Macro-HMM: Identifies market regimes (Calm, Trend, Chaos) from volatility/volume patterns
2. Micro-HMMs: Regime-specific policy heads that specialize behavior within each context

Key Features:
- Macro regime classification using Gaussian HMM on market state features
- Dynamic policy switching based on active regime
- Safe transitions with validation
- Integration with existing ml_service/app.py REST API
"""

import logging
import os
from typing import Any

import joblib
import numpy as np
import pandas as pd
from hmmlearn import hmm
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class ModelNotTrainedError(RuntimeError):
    """Raised when inference is attempted before training."""

    def __init__(self, name: str, action: str):
        super().__init__(f"{name} must be trained before {action}")
        self.name = name
        self.action = action


class ModelArtifactMissingError(FileNotFoundError):
    """Raised when a required model artifact is missing."""

    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


class ActiveRegimeError(RuntimeError):
    """Raised when policy inference occurs without active regime/policy."""

    @classmethod
    def not_set(cls) -> "ActiveRegimeError":
        return cls("no active regime set; call switch() first")

    @classmethod
    def missing_policy(cls, regime: str) -> "ActiveRegimeError":
        return cls(f"no policy loaded for active regime {regime}")


class MacroRegimeHMM:
    """Detects macro market regimes using Gaussian HMM on volatility and volume patterns."""

    REGIME_NAMES = ["Calm", "Trend", "Chaos"]

    def __init__(self, n_states: int = 3, random_state: int = 42):
        """
        Initialize macro regime classifier.

        Args:
            n_states: Number of regimes to detect (default 3: Calm/Trend/Chaos)
            random_state: Random seed for reproducibility
        """
        self.n_states = n_states
        self.regime_names = self.REGIME_NAMES[:n_states]
        self.model = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=200,
            random_state=random_state,
        )
        self.scaler = StandardScaler()
        self.trained = False

    def fit(self, X: np.ndarray) -> "MacroRegimeHMM":
        """
        Train the macro regime model.

        Args:
            X: Feature matrix with shape (n_samples, n_features)
               Expected features: volatility, volume_spikes, drift_score, spread_bp, etc.

        Returns:
            Trained MacroRegimeHMM instance
        """
        logger.info(f"Training MacroRegimeHMM with {len(X)} samples and {X.shape[1]} features")

        # Standardize features
        X_scaled = self.scaler.fit_transform(X)

        # Fit HMM model
        self.model.fit(X_scaled)
        self.trained = True

        logger.info("MacroRegimeHMM training completed")
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict regimes for given feature vectors.

        Args:
            X: Feature matrix with shape (n_samples, n_features)

        Returns:
            Array of regime names with shape (n_samples,)
        """
        if not self.trained:
            raise ModelNotTrainedError("MacroRegimeHMM", "prediction")

        X_scaled = self.scaler.transform(X)
        states = self.model.predict(X_scaled)
        regimes = np.array([self.regime_names[state] for state in states])
        return regimes

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Get regime probabilities for given features.

        Args:
            X: Feature matrix with shape (n_samples, n_features)

        Returns:
            Probability matrix with shape (n_samples, n_states)
        """
        if not self.trained:
            raise ModelNotTrainedError("MacroRegimeHMM", "prediction")

        X_scaled = self.scaler.transform(X)
        _, probs = self.model.decode(X_scaled)
        return probs

    def score(self, X: np.ndarray) -> float:
        """
        Calculate log-likelihood score for the model.

        Args:
            X: Feature matrix for scoring

        Returns:
            Average log-likelihood per sample
        """
        if not self.trained:
            raise ModelNotTrainedError("MacroRegimeHMM", "scoring")

        X_scaled = self.scaler.transform(X)
        return self.model.score(X_scaled) / len(X)

    def get_regime_stats(self) -> dict[str, Any]:
        """
        Get regime detection statistics.

        Returns:
            Dictionary with regime statistics
        """
        if not self.trained:
            return {"trained": False}

        # Get transition matrix
        transmat = self.model.transmat_

        # Calculate regime transition statistics
        regime_stats = {}
        for i, regime in enumerate(self.regime_names):
            regime_stats[regime] = {
                "transitions_from": dict(zip(self.regime_names, transmat[i], strict=False)),
                "mean_state": self.model.means_[i].tolist(),
                "std_state": np.sqrt(self.model.covars_[i]).tolist(),
            }

        return {
            "trained": True,
            "n_regimes": self.n_states,
            "regime_names": self.regime_names,
            "regime_statistics": regime_stats,
        }

    def save(self, path: str) -> None:
        """Save the trained model to disk."""
        bundle = {
            "model": self.model,
            "scaler": self.scaler,
            "n_states": self.n_states,
            "regime_names": self.regime_names,
            "trained": self.trained,
        }
        joblib.dump(bundle, path)
        logger.info(f"MacroRegimeHMM saved to {path}")

    def load(self, path: str) -> "MacroRegimeHMM":
        """Load a trained model from disk."""
        if not os.path.exists(path):
            raise ModelArtifactMissingError(path)

        bundle = joblib.load(path)
        self.model = bundle["model"]
        self.scaler = bundle["scaler"]
        self.n_states = bundle["n_states"]
        self.regime_names = bundle["regime_names"]
        self.trained = bundle["trained"]
        logger.info(f"MacroRegimeHMM loaded from {path}")
        return self


class HierarchicalPolicy:
    """Selects and manages micro-HMM policy heads by active macro regime."""

    def __init__(self, model_dir: str = "ml_service/model_store"):
        """
        Initialize hierarchical policy manager.

        Args:
            model_dir: Directory containing policy files
        """
        self.model_dir = model_dir
        self.active_regime = None
        self.loaded_policies = {}
        self.regime_stats = {}
        self.switch_log = []

    def load_regime_policy(self, regime: str) -> tuple[SGDClassifier, dict]:
        """
        Load a regime-specific policy head.

        Args:
            regime: Regime name (e.g., 'Calm', 'Trend', 'Chaos')

        Returns:
            Tuple of (policy_model, metadata_dict)
        """
        fname = f"policy_{regime}.joblib"
        path = os.path.join(self.model_dir, fname)

        if not os.path.exists(path):
            fallback_fname = "policy_v1.joblib"
            fallback_path = os.path.join(self.model_dir, fallback_fname)
            if os.path.exists(fallback_path):
                logger.warning(f"No policy for regime {regime}, using fallback {fallback_fname}")
                path = fallback_path
            else:
                raise ModelArtifactMissingError(path)

        bundle = joblib.load(path)
        policy = bundle.get("policy", bundle)  # Handle both formats
        metadata = bundle.get("metadata", {"regime": regime})

        logger.info(f"Loaded policy for regime {regime} from {path}")
        return policy, metadata

    def switch(self, new_regime: str) -> bool:
        """
        Switch to a new regime policy if different from current.

        Args:
            new_regime: Target regime name

        Returns:
            True if switch occurred, False if already active
        """
        if new_regime == self.active_regime:
            return False

        try:
            policy, metadata = self.load_regime_policy(new_regime)
        except _SUPPRESSIBLE_EXCEPTIONS:
            logger.exception("Failed to switch to regime %s", new_regime)
            return False

        self.loaded_policies[new_regime] = (policy, metadata)
        old_regime = self.active_regime
        self.active_regime = new_regime

        switch_event = {
            "timestamp": pd.Timestamp.now(),
            "from_regime": old_regime,
            "to_regime": new_regime,
            "metadata": metadata,
        }
        self.switch_log.append(switch_event)
        logger.info("Switched from %s to %s", old_regime, new_regime)
        return True

    def infer(self, features: np.ndarray) -> dict[str, Any]:
        """
        Make inference using the active regime policy.

        Args:
            features: Feature vector for decision

        Returns:
            Decision dictionary with action, confidence, and regime
        """
        if self.active_regime is None:
            raise ActiveRegimeError.not_set()

        if self.active_regime not in self.loaded_policies:
            raise ActiveRegimeError.missing_policy(self.active_regime)

        policy, metadata = self.loaded_policies[self.active_regime]

        try:
            # Get decision probabilities
            if hasattr(policy, "predict_proba"):
                probs = policy.predict_proba(features.reshape(1, -1))[0]
            else:
                # Fallback for models without predict_proba
                decision = policy.decision_function(features.reshape(1, -1))
                if decision.ndim == 1:
                    # Binary case
                    prob_pos = 1 / (1 + np.exp(-decision[0]))
                    probs = np.array([1 - prob_pos, prob_pos])
                else:
                    # Multi-class
                    e_decision = np.exp(decision - decision.max())
                    probs = e_decision / e_decision.sum()

            # Get action (centered around 0: -1, 0, 1)
            action_idx = np.argmax(probs)
            action = action_idx - 1  # Convert {0,1,2} to {-1,0,1}
            confidence = float(probs[action_idx])

            return {
                "action": int(action),
                "confidence": confidence,
                "regime": self.active_regime,
                "probabilities": probs.tolist(),
                "metadata": metadata,
            }

        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            logger.exception("Inference failed for regime %s", self.active_regime)
            # Return safe fallback
            return {
                "action": 0,  # HOLD
                "confidence": 0.0,
                "regime": self.active_regime,
                "probabilities": [0.0, 0.0, 0.0],
                "error": str(exc),
            }

    def get_stats(self) -> dict[str, Any]:
        """
        Get hierarchical policy statistics.

        Returns:
            Dictionary with policy and switching statistics
        """
        switch_count = len(self.switch_log)
        regime_counts = {}
        if self.switch_log:
            for event in self.switch_log:
                regime = event["to_regime"]
                regime_counts[regime] = regime_counts.get(regime, 0) + 1

        return {
            "active_regime": self.active_regime,
            "loaded_regimes": list(self.loaded_policies.keys()),
            "total_switches": switch_count,
            "regime_switch_counts": regime_counts,
            "recent_switches": self.switch_log[-10:] if self.switch_log else [],
        }

    def export_switch_log(self, path: str = "data/processed/switch_events.csv") -> None:
        """
        Export switch event log to CSV.

        Args:
            path: Output file path
        """
        if not self.switch_log:
            logger.info("No switch events to export")
            return

        os.makedirs(os.path.dirname(path), exist_ok=True)
        df = pd.DataFrame(self.switch_log)
        df.to_csv(path, index=False)
        logger.info(f"Switch log exported to {path}")


# Global instance for easy access (similar to existing global logger pattern)
_global_hierarchy = None


def get_hierarchical_policy(
    model_dir: str = "ml_service/model_store",
) -> HierarchicalPolicy:
    """Get or create global hierarchical policy instance."""
    global _global_hierarchy
    if _global_hierarchy is None or _global_hierarchy.model_dir != model_dir:
        _global_hierarchy = HierarchicalPolicy(model_dir)
    return _global_hierarchy
