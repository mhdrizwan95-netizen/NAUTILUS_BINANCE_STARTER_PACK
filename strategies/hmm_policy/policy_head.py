#!/usr/bin/env python3
# strategies/hmm_policy/policy_head.py — M15: Neural policy head for online fine-tuning
import numpy as np
from typing import Dict, List, Optional, Tuple
import pickle
from pathlib import Path

class TinyMLP:
    """
    Tiny neural network for buy/sell probability estimation.
    Single hidden layer with careful initialization and safe gradients.
    Used for online policy adaptation based on trade outcomes.
    """

    def __init__(self, d_in: int, d_hidden: int = 16, seed: int = 7):
        """
        Initialize neural network.

        Args:
            d_in: Input dimension (feature vector size)
            d_hidden: Hidden layer size
            seed: Random seed for reproducibility
        """
        self.d_in = d_in
        self.d_hidden = d_hidden

        rng = np.random.default_rng(seed)

        # Xavier initialization for stable gradients
        xavier_scale_in = np.sqrt(2.0 / d_in)
        xavier_scale_hidden = np.sqrt(2.0 / d_hidden)

        self.W1 = rng.normal(0, xavier_scale_in, (d_in, d_hidden)).astype(np.float32)
        self.b1 = np.zeros(d_hidden, dtype=np.float32)
        self.W2 = rng.normal(0, xavier_scale_hidden, (d_hidden, 1)).astype(np.float32)
        self.b2 = np.zeros(1, dtype=np.float32)

        # Track gradient norms for safety monitoring
        self.last_grad_norm = 0.0
        self.update_count = 0

    def _forward(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Forward pass.

        Args:
            x: Input batch (batch_size, d_in)

        Returns:
            Tuple of (hidden_activation, output_prob)
        """
        # Ensure correct input shape
        if x.ndim == 1:
            x = x.reshape(1, -1)

        # Hidden layer: tanh activation
        h_pre = x @ self.W1 + self.b1
        h = np.tanh(h_pre)

        # Output layer: sigmoid for probability
        z = h @ self.W2 + self.b2
        y = 1.0 / (1.0 + np.exp(-z))

        return h, y

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        """
        Predict probability of BUY action.

        Args:
            x: Input features (can be 1D or 2D)

        Returns:
            Probability of buying (shape matches input batch size)
        """
        _, y = self._forward(x)
        return y.ravel()

    def step(self, x: np.ndarray, y_true: np.ndarray, lr: float = 1e-4, clip: float = 0.1):
        """
        Single gradient step on batch.

        Args:
            x: Input batch (batch_size, d_in)
            y_true: True labels (0=SELL, 1=BUY) (batch_size,)
            lr: Learning rate
            clip: Gradient clipping threshold
        """
        if x.ndim == 1:
            x = x.reshape(1, -1)

        batch_size = x.shape[0]

        # Forward pass
        h, y = self._forward(x)

        # Binary cross-entropy loss
        # Clip predictions for numerical stability
        eps = 1e-15
        y_clipped = np.clip(y.ravel(), eps, 1 - eps)
        y_true_clipped = np.clip(y_true.astype(float), 0.0, 1.0)

        loss = -np.mean(y_true_clipped * np.log(y_clipped) +
                       (1 - y_true_clipped) * np.log(1 - y_clipped))

        # Backward pass
        dz = (y - y_true.reshape(-1, 1))  # (batch_size, 1)

        # Output layer gradients
        dW2 = (h.T @ dz) / batch_size  # (d_hidden, 1)
        db2 = dz.mean(axis=0)          # (1,)

        # Hidden layer gradients
        dh = dz @ self.W2.T * (1 - h**2)  # (batch_size, d_hidden)
        dW1 = (x.T @ dh) / batch_size      # (d_in, d_hidden)
        db1 = dh.mean(axis=0)              # (d_hidden,)

        # Collect all gradients
        grads = [dW1, db1, dW2, db2]
        grad_norm = np.sqrt(sum(np.sum(g**2) for g in grads))
        self.last_grad_norm = float(grad_norm)

        # Gradient clipping
        for g in grads:
            np.clip(g, -clip, clip, out=g)

        # Parameter updates
        self.W1 -= lr * dW1
        self.b1 -= lr * db1
        self.W2 -= lr * dW2
        self.b2 -= lr * db2

        self.update_count += 1

    def get_weights_norms(self) -> Dict[str, float]:
        """Get L2 norms of weight matrices for monitoring."""
        return {
            'W1_norm': float(np.sqrt(np.sum(self.W1**2))),
            'W2_norm': float(np.sqrt(np.sum(self.W2**2))),
            'b1_norm': float(np.sqrt(np.sum(self.b1**2))),
            'b2_norm': float(np.sqrt(np.sum(self.b2**2)))
        }

    def get_stats(self) -> Dict[str, float]:
        """Get network statistics."""
        weights_stats = self.get_weights_norms()
        return {
            **weights_stats,
            'update_count': self.update_count,
            'last_grad_norm': self.last_grad_norm,
            'd_in': self.d_in,
            'd_hidden': self.d_hidden
        }

    def save_weights(self, filepath: Path):
        """Save model weights to file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        weights = {
            'W1': self.W1,
            'b1': self.b1,
            'W2': self.W2,
            'b2': self.b2,
            'update_count': self.update_count,
            'd_in': self.d_in,
            'd_hidden': self.d_hidden
        }
        with open(filepath, 'wb') as f:
            pickle.dump(weights, f)

    def load_weights(self, filepath: Path) -> bool:
        """Load model weights from file."""
        if not filepath.exists():
            return False

        try:
            with open(filepath, 'rb') as f:
                weights = pickle.load(f)

            # Validate dimensions
            if (weights.get('d_in') != self.d_in or
                weights.get('d_hidden') != self.d_hidden):
                return False

            self.W1 = weights['W1']
            self.b1 = weights['b1']
            self.W2 = weights['W2']
            self.b2 = weights['b2']
            self.update_count = weights.get('update_count', 0)

            return True
        except (pickle.PickleError, KeyError, ValueError):
            return False

    def reset_weights(self, seed: int = 7):
        """Reset weights to initial values."""
        old_d_in = self.d_in
        old_d_hidden = self.d_hidden
        self.__init__(self.d_in, self.d_hidden, seed)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return f"TinyMLP(d_in={self.d_in}, hidden={self.d_hidden}, updates={stats['update_count']}, W2_norm={stats['W2_norm']:.4f})"
