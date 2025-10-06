#!/usr/bin/env python3
"""
strategies/hmm_policy/covariance_allocator.py — M18: Multi-Symbol Covariance-Aware Risk Allocation

Enables coordinated trading across correlated symbols with dynamic position sizing
governed by a rolling covariance matrix. Each asset's exposure adjusts automatically
so that portfolio variance stays constant while capital flows toward uncorrelated
or strong-edge instruments.

Key Features:
- Rolling covariance estimation over time windows
- Risk parity through inverse covariance weighting
- Target variance scaling for absolute risk control
- Graceful fallback to equal weighting
- Integration with hierarchical policy system
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CovarianceAllocator:
    """
    Allocates per-symbol weights using rolling covariance and risk budget to maintain
    constant portfolio variance across multiple correlated assets.

    Behavior:
    - Computes rolling covariance matrix from recent returns
    - Uses risk parity (inverse covariance) weighting as baseline
    - Scales weights to maintain target portfolio variance
    - Falls back to equal weighting when covariance data insufficient

    Integration:
    - Update with realized returns after each trade
    - Query weights() before sizing new positions
    - Maintains total portfolio volatility regardless of correlation structure
    """

    def __init__(self, window: int = 500, target_var: float = 0.0001, min_periods: int = 50):
        """
        Initialize covariance-aware allocator.

        Args:
            window: Rolling window for covariance estimation (number of observations)
            target_var: Target portfolio variance (e.g., 0.0001 = 1% volatility squared)
            min_periods: Minimum observations needed before covariance-based weighting
        """
        self.window = window
        self.target_var = target_var
        self.min_periods = min_periods

        # Per-symbol return buffers
        self.return_buffers: Dict[str, List[float]] = {}

        # Cache for computed weights and covariance matrix
        self._weights_cache: Optional[Dict[str, float]] = None
        self._cov_matrix_cache: Optional[np.ndarray] = None
        self._last_update = 0

        logger.info(f"Initialized CovarianceAllocator: window={window}, target_var={target_var*1e4:.3f}bps²")

    def update(self, symbol: str, ret: float, timestamp: Optional[float] = None) -> None:
        """
        Update return data for a symbol.

        Args:
            symbol: Symbol name (e.g., 'BTCUSDT')
            ret: Realized return since last trade (decimal, e.g., 0.01 for 1%)
            timestamp: Optional timestamp for temporal ordering
        """
        if symbol not in self.return_buffers:
            self.return_buffers[symbol] = []
            logger.info(f"Started tracking returns for {symbol}")

        self.return_buffers[symbol].append(ret)

        # Maintain rolling window
        if len(self.return_buffers[symbol]) > self.window:
            self.return_buffers[symbol].pop(0)

        # Invalidate cache
        self._weights_cache = None
        self._cov_matrix_cache = None

        # Log occasional updates
        total_updates = sum(len(buf) for buf in self.return_buffers.values())
        if total_updates % 100 == 0:
            logger.debug(f"CovarianceAllocator: {total_updates} total updates, {len(self.return_buffers)} symbols")

    def weights(self) -> Dict[str, float]:
        """
        Compute optimal weights using covariance-based risk parity.

        Returns:
            Dictionary mapping symbol names to weight multipliers (0-1 range)
        """
        symbols = list(self.return_buffers.keys())
        n_symbols = len(symbols)

        if n_symbols == 0:
            logger.warning("No symbols tracked, cannot compute weights")
            return {}

        # Check if we have sufficient data for each symbol
        max_len = max(len(buf) for buf in self.return_buffers.values())
        if max_len < self.min_periods:
            logger.info(f"Insufficient data ({max_len} < {self.min_periods}), using equal weights")
            return {s: 1.0 / n_symbols for s in symbols}

        # Ensure all symbols have the same number of observations
        min_len = min(len(buf) for buf in self.return_buffers.values())
        if min_len < self.min_periods:
            # Drop symbols with insufficient data
            symbols = [s for s in symbols if len(self.return_buffers[s]) >= self.min_periods]
            if len(symbols) < 2:
                logger.info("Not enough symbols with sufficient data, using equal weights")
                return {s: 1.0 / len(self.return_buffers) for s in self.return_buffers.keys()}
            n_symbols = len(symbols)

        # Build DataFrame with aligned windows
        aligned_data = {}
        for symbol in symbols:
            buf = self.return_buffers[symbol]
            aligned_data[symbol] = buf[-min_len:]  # Most recent observations

        df_returns = pd.DataFrame(aligned_data)

        try:
            # Compute covariance matrix
            cov_matrix = df_returns.cov().values
            self._cov_matrix_cache = cov_matrix

            # Handle numerical issues
            if np.any(np.isnan(cov_matrix)) or np.any(np.isinf(cov_matrix)):
                logger.warning("Invalid covariance values detected, using equal weights")
                weights = {s: 1.0 / n_symbols for s in symbols}
            else:
                # Risk parity weights via inverse covariance
                try:
                    # Regularize covariance matrix for numerical stability
                    reg_cov = cov_matrix + np.eye(n_symbols) * 1e-8

                    # Inverse covariance matrix
                    inv_cov = np.linalg.pinv(reg_cov)

                    # Risk parity weights: proportional to inverse variance contribution
                    marginal_risk = inv_cov.sum(axis=1)
                    raw_weights = marginal_risk / marginal_risk.sum()

                    # Scale to achieve target portfolio variance
                    port_var = raw_weights.T @ cov_matrix @ raw_weights
                    if port_var > 0:
                        scale_factor = np.sqrt(self.target_var / port_var)
                        scaled_weights = raw_weights * scale_factor
                    else:
                        logger.warning("Zero portfolio variance computed, using equal weights")
                        scaled_weights = np.ones(n_symbols) / n_symbols

                    # Ensure non-negative and sum to <= 1 for safety
                    scaled_weights = np.maximum(scaled_weights, 0)
                    if scaled_weights.sum() > 1.0:
                        scaled_weights = scaled_weights / scaled_weights.sum()

                    weights = {s: float(w) for s, w in zip(symbols, scaled_weights)}

                except np.linalg.LinAlgError as e:
                    logger.warning(f"Covariance matrix inversion failed: {e}, using equal weights")
                    weights = {s: 1.0 / n_symbols for s in symbols}

        except Exception as e:
            logger.error(f"Error computing covariance weights: {e}, using equal weights")
            weights = {s: 1.0 / n_symbols for s in self.return_buffers.keys()}

        self._weights_cache = weights
        logger.debug(f"Computed weights: {weights}")
        return weights

    def portfolio_variance(self) -> float:
        """
        Calculate current portfolio variance.

        Returns:
            Portfolio variance (annualized if returns are daily)
        """
        weights = self.weights()
        if not weights or self._cov_matrix_cache is None:
            return 0.0

        symbols = list(weights.keys())
        w_vec = np.array([weights[s] for s in symbols])

        try:
            port_var = w_vec.T @ self._cov_matrix_cache @ w_vec
            return max(0.0, float(port_var))  # Ensure non-negative
        except Exception as e:
            logger.error(f"Error computing portfolio variance: {e}")
            return 0.0

    def correlation_matrix(self) -> pd.DataFrame:
        """
        Get correlation matrix for analyzed symbols.

        Returns:
            DataFrame with correlation coefficients
        """
        symbols = list(self.return_buffers.keys())
        if len(symbols) < 2:
            return pd.DataFrame()

        try:
            min_len = min(len(buf) for buf in self.return_buffers.values())
            data = {s: self.return_buffers[s][-min_len:] for s in symbols}
            df = pd.DataFrame(data)
            return df.corr()
        except Exception as e:
            logger.error(f"Error computing correlation matrix: {e}")
            return pd.DataFrame()

    def eigen_analysis(self) -> Dict[str, Any]:
        """
        Perform eigenvalue analysis of the covariance matrix.

        Returns:
            Dictionary with eigenvalues, eigenvectors, and explained variance
        """
        if self._cov_matrix_cache is None or len(self.return_buffers) < 2:
            return {"eigenvalues": [], "explained_var_ratio": []}

        try:
            eigenvals, eigenvecs = np.linalg.eigh(self._cov_matrix_cache)

            # Sort in descending order
            idx = np.argsort(eigenvals)[::-1]
            eigenvals = eigenvals[idx]
            eigenvecs = eigenvecs[:, idx]

            # Explained variance ratios
            total_var = eigenvals.sum()
            explained_var_ratio = eigenvals / total_var if total_var > 0 else np.zeros_like(eigenvals)

            return {
                "eigenvalues": eigenvals.tolist(),
                "eigenvectors": eigenvecs.tolist(),
                "explained_var_ratio": explained_var_ratio.tolist(),
                "effective_rank": np.sum(eigenvals > 1e-8)  # Number of significant components
            }
        except Exception as e:
            logger.error(f"Error in eigen analysis: {e}")
            return {"eigenvalues": [], "explained_var_ratio": []}

    def debug_state(self) -> Dict[str, Any]:
        """
        Get current state for debugging and monitoring.

        Returns:
            Dictionary with buffer lengths, weights, and diagnostic info
        """
        symbols = list(self.return_buffers.keys())
        buffer_info = {s: len(buf) for s, buf in self.return_buffers.items()}

        weights = self.weights() if self._weights_cache is None else self._weights_cache

        eigen_info = self.eigen_analysis()

        return {
            "symbols_tracked": symbols,
            "buffer_lengths": buffer_info,
            "current_weights": weights,
            "portfolio_variance": self.portfolio_variance(),
            "target_variance": self.target_var,
            "eigen_summary": {
                "largest_eigenvalue": eigen_info.get("eigenvalues", [0])[0],
                "explained_var_ratio": eigen_info.get("explained_var_ratio", [0])[:3],  # Top 3
                "effective_rank": eigen_info.get("effective_rank", 0)
            },
            "correlation_matrix_available": len(symbols) > 1
        }

    def reset(self) -> None:
        """Reset all buffers and caches."""
        self.return_buffers.clear()
        self._weights_cache = None
        self._cov_matrix_cache = None
        self._last_update = 0
        logger.info("CovarianceAllocator state reset")

    def export_weights_history(self, filepath: str) -> None:
        """
        Export historical weight allocations to CSV.

        Args:
            filepath: Output CSV file path
        """
        # This would require additional history tracking in production
        # For now, just export current weights with timestamp
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        weights = self.weights()
        timestamp = datetime.now().isoformat()

        record = {"timestamp": timestamp, **weights}

        # Append to CSV or create new
        try:
            if os.path.exists(filepath):
                df_existing = pd.read_csv(filepath)
                df_new = pd.DataFrame([record])
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.to_csv(filepath, index=False)
            else:
                df = pd.DataFrame([record])
                df.to_csv(filepath, index=False)

            logger.info(f"Exported weights to {filepath}")
        except Exception as e:
            logger.error(f"Failed to export weights: {e}")


# Global allocator instance (similar to ML service pattern)
_global_allocator = None


def get_covariance_allocator(window: int = 500, target_var: float = 0.0001) -> CovarianceAllocator:
    """
    Get or create global covariance allocator instance.

    Args:
        window: Rolling window size
        target_var: Target portfolio variance

    Returns:
        Global CovarianceAllocator instance
    """
    global _global_allocator
    if _global_allocator is None or _global_allocator.window != window or _global_allocator.target_var != target_var:
        _global_allocator = CovarianceAllocator(window=window, target_var=target_var)
    return _global_allocator
