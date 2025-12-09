"""Linear Thompson Sampling Bandit for contextual parameter selection."""

import numpy as np
from typing import Optional


class LinTS:
    """Linear Thompson Sampling contextual bandit.
    
    Uses Bayesian linear regression with Thompson sampling to select
    the best arm (preset) given context features.
    """
    
    def __init__(self, d: int, l2: float = 1.0, alpha: float = 1.0):
        """Initialize the bandit.
        
        Args:
            d: Feature dimension
            l2: L2 regularization parameter
            alpha: Variance scaling for Thompson sampling
        """
        self.d = d
        self.l2 = l2
        self.alpha = alpha
        
        # Prior: N(0, I/l2)
        # Posterior precision and mean for each arm
        self._arms: dict[int, dict] = {}
    
    def _get_arm(self, arm: int) -> dict:
        """Get or initialize arm posterior params."""
        if arm not in self._arms:
            self._arms[arm] = {
                "A": self.l2 * np.eye(self.d),  # Precision matrix
                "b": np.zeros(self.d),           # Weighted sum of rewards
                "n": 0,                          # Number of observations
            }
        return self._arms[arm]
    
    def update(self, arm: int, x: np.ndarray, reward: float) -> None:
        """Update posterior for an arm given observation.
        
        Args:
            arm: Arm index
            x: Feature vector at time of pull
            reward: Observed reward
        """
        state = self._get_arm(arm)
        x = np.array(x).flatten()
        
        # Update precision: A += x @ x.T
        state["A"] += np.outer(x, x)
        
        # Update weighted rewards: b += reward * x
        state["b"] += reward * x
        state["n"] += 1
    
    def choose(self, X: np.ndarray) -> int:
        """Choose an arm using Thompson sampling.
        
        Args:
            X: Context matrix of shape (K, d) where K is number of arms
            
        Returns:
            Index of chosen arm
        """
        K = X.shape[0]
        samples = np.zeros(K)
        
        for arm in range(K):
            state = self._get_arm(arm)
            x = X[arm]
            
            # Compute posterior mean and variance
            try:
                A_inv = np.linalg.inv(state["A"])
            except np.linalg.LinAlgError:
                A_inv = np.linalg.pinv(state["A"])
            
            # Posterior mean: theta = A^-1 @ b
            theta_mean = A_inv @ state["b"]
            
            # Posterior covariance for prediction: alpha^2 * x.T @ A^-1 @ x
            var = self.alpha * np.sqrt(x @ A_inv @ x)
            
            # Sample from posterior predictive
            samples[arm] = x @ theta_mean + var * np.random.randn()
        
        return int(np.argmax(samples))
    
    def expected_reward(self, arm: int, x: np.ndarray) -> float:
        """Compute expected reward for an arm given context.
        
        Args:
            arm: Arm index
            x: Feature vector
            
        Returns:
            Expected reward
        """
        state = self._get_arm(arm)
        x = np.array(x).flatten()
        
        try:
            A_inv = np.linalg.inv(state["A"])
        except np.linalg.LinAlgError:
            A_inv = np.linalg.pinv(state["A"])
        
        theta = A_inv @ state["b"]
        return float(x @ theta)
