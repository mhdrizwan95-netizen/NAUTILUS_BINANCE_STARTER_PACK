#!/usr/bin/env python3
# strategies/hmm_policy/online_trainer.py — M15: Safe online policy fine-tuning coordinator
import numpy as np
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from collections import deque

from .policy_head import TinyMLP
from .feedback import FeedbackLogger, FeedbackMetrics
from .config import HMMPolicyConfig

class OnlineFineTuner:
    """
    Safe online policy fine-tuning coordinator.
    Manages TinyMLP updates with safety rails, cooldowns, and performance monitoring.
    """

    def __init__(self, model: TinyMLP, lr: float = 1e-4, batch_size: int = 64,
                 hold_band: float = 0.1, cool_s: int = 60, buffer_max: int = 5000,
                 early_stop_win_rate: float = 0.40, early_stop_trade_count: int = 50):
        """
        Initialize online fine-tuner.

        Args:
            model: TinyMLP model to fine-tune
            lr: Learning rate (very small for safety)
            batch_size: Mini-batch size for updates
            hold_band: HOLD decision band around 0.5 probability
            cool_s: Cooldown between updates (seconds)
            buffer_max: Max experience buffer size
            early_stop_win_rate: Win rate threshold for auto-pausing
            early_stop_trade_count: Recent trades to check for early stopping
        """
        self.model = model
        self.lr = lr
        self.batch_size = batch_size
        self.hold_band = hold_band
        self.cool_s = cool_s
        self.buffer_max = buffer_max

        # Experience buffer
        self.x_buffer = deque(maxlen=buffer_max)
        self.y_buffer = deque(maxlen=buffer_max)

        # Safety tracking
        self.last_update_ts = 0.0
        self.early_stop_win_rate = early_stop_win_rate
        self.early_stop_trade_count = early_stop_trade_count
        self.is_enabled = True  # Can be disabled via Ops API
        self.total_updates = 0

        # Performance history for safety checks
        self.recent_pnls = deque(maxlen=early_stop_trade_count)
        self.recent_predictions = deque(maxlen=early_stop_trade_count)

        # Snapshot for rollback
        self.snapshot_dir = Path("data/processed/policy_snapshots")
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Load existing snapshot if available
        self.load_latest_snapshot()

    def observe(self, feats_vec: np.ndarray, side: str, delta_pnl: float):
        """
        Observe a trade outcome for potential online learning.

        Args:
            feats_vec: Feature vector used for decision
            side: Trade side (BUY/SELL/HOLD)
            delta_pnl: Realized PnL outcome
        """
        if not self.is_enabled or side == "HOLD":
            return

        # Convert to supervised learning target
        # Reward shaping: positive outcomes reinforce the action taken
        if side == "BUY":
            # If win: should have bought (1), if loss: should not have bought (0)
            target = 1.0 if delta_pnl > 0 else 0.0
        else:  # side == "SELL"
            # If win: should have sold (0, since 1=BUY), if loss: should have bought (1)
            target = 0.0 if delta_pnl > 0 else 1.0

        # Store in buffers
        self.x_buffer.append(feats_vec.copy())
        self.y_buffer.append(target)

        # Track for safety monitoring
        self.recent_pnls.append(delta_pnl)
        pred_prob = self.model.predict_proba(feats_vec)[0]
        self.recent_predictions.append((pred_prob, side))

    def maybe_update(self, now: Optional[float] = None) -> bool:
        """
        Conditionally perform an online model update if conditions are met.

        Args:
            now: Current timestamp (uses time.time() if None)

        Returns:
            True if update was performed
        """
        if not self.is_enabled:
            return False

        if now is None:
            now = time.time()

        # Check cooldown
        if (now - self.last_update_ts) < self.cool_s:
            return False

        # Check if we have enough data
        if len(self.x_buffer) < self.batch_size:
            return False

        # Safety check: recent performance acceptable?
        if not self._performance_check_ok():
            self.is_enabled = False
            print(f"[OnlineFineTuner] Auto-disabled: recent performance below threshold")
            return False

        # Perform update
        return self._do_update()

    def _do_update(self) -> bool:
        """Perform the actual model update."""
        # Sample batch from recent experiences
        available = len(self.x_buffer)
        if available < self.batch_size:
            return False

        # Sample most recent batch (temporal bias toward recent experiences)
        indices = np.arange(max(0, available - self.batch_size), available)
        X_batch = np.array([self.x_buffer[i] for i in indices])
        y_batch = np.array([self.y_buffer[i] for i in indices])

        # Update model
        self.model.step(X_batch, y_batch, lr=self.lr, clip=0.05)

        self.last_update_ts = time.time()
        self.total_updates += 1

        # Save safety snapshot every 10 updates
        if self.total_updates % 10 == 0:
            self.save_snapshot()

        return True

    def _performance_check_ok(self) -> bool:
        """Check if recent performance justifies continued online learning."""
        if len(self.recent_pnls) < 10:
            return True  # Need minimum sample

        # Calculate recent win rate
        wins = sum(1 for pnl in self.recent_pnls if pnl > 0)
        win_rate = wins / len(self.recent_pnls)

        return win_rate >= self.early_stop_win_rate

    def score(self, feats_vec: np.ndarray) -> float:
        """
        Score feature vector for buy probability, applying HOLD band.

        Returns:
            Probability between 0.0 and 1.0 (HOLD mapped to 0.5)
        """
        if feats_vec.ndim == 1:
            feats_vec = feats_vec.reshape(1, -1)

        prob = self.model.predict_proba(feats_vec)[0]

        # Apply HOLD band
        if abs(prob - 0.5) <= self.hold_band:
            return 0.5  # HOLD decision

        return prob

    def set_enabled(self, enabled: bool):
        """Enable/disable online learning."""
        self.is_enabled = enabled

    def reset_buffer(self):
        """Clear experience buffer (useful for new sessions)."""
        self.x_buffer.clear()
        self.y_buffer.clear()

    def reset_performance_history(self):
        """Reset performance tracking."""
        self.recent_pnls.clear()
        self.recent_predictions.clear()

    def save_snapshot(self):
        """Save current model state to timestamped file."""
        timestamp = int(time.time() * 1e9)  # nanoseconds
        filepath = self.snapshot_dir / f"policy_snapshot_{timestamp}.pkl"
        self.model.save_weights(filepath)

    def load_latest_snapshot(self) -> bool:
        """Load most recent snapshot."""
        if not self.snapshot_dir.exists():
            return False

        snapshots = list(self.snapshot_dir.glob("policy_snapshot_*.pkl"))
        if not snapshots:
            return False

        # Find latest by timestamp in filename
        latest = max(snapshots, key=lambda p: int(p.stem.split('_')[-1]))
        return self.model.load_weights(latest)

    def get_stats(self) -> Dict[str, float]:
        """Get trainer statistics."""
        return {
            'enabled': 1.0 if self.is_enabled else 0.0,
            'total_updates': self.total_updates,
            'buffer_size': len(self.x_buffer),
            'last_update_age_s': time.time() - self.last_update_ts,
            'recent_win_rate': (sum(1 for pnl in self.recent_pnls if pnl > 0) /
                               max(1, len(self.recent_pnls))),
            'model_updates': self.model.update_count,
            'last_grad_norm': self.model.last_grad_norm
        }

    def get_performance_summary(self) -> Dict[str, float]:
        """Get detailed performance metrics."""
        if not self.recent_pnls:
            return {'insufficient_data': 1.0}

        pnls = list(self.recent_pnls)
        returns = [pnl for pnl in pnls if pnl != 0]

        return {
            'avg_pnl': np.mean(pnls),
            'total_pnl': sum(pnls),
            'win_rate': sum(1 for pnl in pnls if pnl > 0) / len(pnls),
            'profit_factor': (sum(p for p in pnls if p > 0) /
                            max(0.001, abs(sum(p for p in pnls if p < 0)))),
            'sharpe_like': (np.mean(pnls) / max(0.001, np.std(pnls))) if pnls else 0.0,
            'max_drawdown': min(0.0, min(np.cumsum(pnls))) if pnls else 0.0
        }

    def predict_action(self, feats_vec: np.ndarray, threshold: float = 0.55) -> str:
        """
        Predict action based on model score.

        Args:
            feats_vec: Feature vector
            threshold: Confidence threshold for BUY/SELL (vs HOLD)

        Returns:
            Action string: 'BUY', 'SELL', or 'HOLD'
        """
        prob = self.score(feats_vec)

        if prob >= threshold:
            return 'BUY'
        elif prob <= (1.0 - threshold):
            return 'SELL'
        else:
            return 'HOLD'

    def __repr__(self) -> str:
        stats = self.get_stats()
        enabled = "ENABLED" if self.is_enabled else "DISABLED"
        return f"OnlineFineTuner({enabled}, updates={stats['total_updates']}, buffer={stats['buffer_size']})"

# Global trainer instance
_global_trainer: Optional['OnlineFineTuner'] = None

def get_global_online_trainer(feature_dim: int, data_dir: Path) -> 'OnlineFineTuner':
    """Get or create global online trainer instance."""
    global _global_trainer
    if _global_trainer is None:
        # Initialize with feature dimension from config
        model = TinyMLP(d_in=feature_dim, d_hidden=16, seed=7)
        _global_trainer = OnlineFineTuner(model, lr=1e-4)

    return _global_trainer
