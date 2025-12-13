import numpy as np
import logging

logger = logging.getLogger(__name__)

class RecursiveLeastSquares:
    """
    Online Linear Regression using Recursive Least Squares (RLS).
    Estimates y = beta * x + alpha
    """
    def __init__(self, n_features: int = 1, l2: float = 0.01, forget: float = 1.0):
        """
        :param n_features: Number of independent variables (x).
        :param l2: Regularization factor (L2 ridge).
        :param forget: Forgetting factor (lambda). 1.0 = Infinite memory (static), < 1.0 = adaptive.
        """
        self.n = n_features
        self.forget = forget
        
        # Initialize Inverse Correlation Matrix (P) and Estimator (theta)
        # P = inv(X.T @ X + l2*I)
        # We start with a large identity matrix (P = (1/delta) * I) implies small initial certainty
        self.P = np.eye(n_features) * 1000.0 
        self.theta = np.zeros(n_features)
        
        # Stats
        self.n_obs = 0

    def update(self, x: np.ndarray, y: float):
        """
        Update the estimator with a single observation.
        x: shape (n_features,)
        y: scalar
        """
        # Make sure x is numpy array
        x = np.array(x)
        if x.shape != (self.n,):
            raise ValueError(f"Expected x shape ({self.n},), got {x.shape}")

        # Prediction before update (a priori)
        y_pred = np.dot(self.theta, x)
        error = y - y_pred
        
        # Gain Factor (Kalman Gain like)
        # K = (P @ x) / (lambda + x.T @ P @ x)
        Px = np.dot(self.P, x)
        denom = self.forget + np.dot(x, Px)
        K = Px / denom
        
        # Update Estimates
        # theta_new = theta + K * error
        self.theta = self.theta + (K * error)
        
        # Update Covariance Matrix
        # P_new = (P - K @ x.T @ P) / lambda
        # Outer product K * Px.T is (n,1)*(1,n) = (n,n)
        term2 = np.outer(K, Px)
        self.P = (self.P - term2) / self.forget
        
        self.n_obs += 1
        
        return y_pred

    def predict(self, x: np.ndarray) -> float:
        return float(np.dot(self.theta, x))
    
    @property
    def slope(self):
        return self.theta[0] if self.n >= 1 else 0.0
        
    @property
    def intercept(self):
        # Assumes intercept is the second feature (augmented X with 1.0)
        return self.theta[1] if self.n >= 2 else 0.0


class CointegrationModel:
    """
    Manages the relationship between two assets: Target (Y) and Hedge (X).
    Y = beta * X + epsilon
    Spread = Y - beta * X
    """
    def __init__(self, target_sym: str, hedge_sym: str, learning_rate: float = 0.995):
        self.target = target_sym
        self.hedge = hedge_sym
        
        # RLS Model: Y = beta*X + alpha*1
        # Features = [Price_X, 1.0]
        self.rls = RecursiveLeastSquares(n_features=2, forget=learning_rate)
        
        self.spread_history = []
        self.spread_mean = 0.0
        self.spread_std = 0.0
        
        # Z-Score window (computation window for spread normalization)
        self.window = 300 

    def update(self, price_y: float, price_x: float) -> dict:
        """
        Updates the model and returns the current Z-Score.
        """
        # Log prices usually preferred for cointegration
        ly = np.log(price_y)
        lx = np.log(price_x)
        
        # Features: [LogPriceX, Intercept]
        features = np.array([lx, 1.0])
        
        # Update RLS
        self.rls.update(features, ly)
        
        # Calculate Current Spread (Residual)
        # Spread = Actual_Y - Predicted_Y
        pred_y = self.rls.predict(features)
        spread = ly - pred_y
        
        # Update Z-Score Stats (Simple rolling window)
        self.spread_history.append(spread)
        if len(self.spread_history) > self.window:
            self.spread_history.pop(0)
            
        if len(self.spread_history) > 30:
            self.spread_mean = np.mean(self.spread_history)
            self.spread_std = np.std(self.spread_history)
            
        z_score = 0.0
        if self.spread_std > 1e-9:
            z_score = (spread - self.spread_mean) / self.spread_std
            
        return {
            "beta": self.rls.slope,
            "spread": spread,
            "z_score": z_score,
            "residual": spread # Same as spread here
        }
