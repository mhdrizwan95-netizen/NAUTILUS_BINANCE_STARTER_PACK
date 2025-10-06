#!/usr/bin/env python3
# strategies/hmm_policy/risk_covariance.py — M14: Cross-symbol return covariance tracker
import numpy as np
from collections import deque
from typing import List, Dict, Optional, Tuple

class CovarianceTracker:
    """
    Tracks rolling log returns for multiple symbols and computes covariance/correlation matrices.
    Used for portfolio-level risk management across BTC and ETH.
    """

    def __init__(self, symbols: List[str], window: int = 300):
        self.symbols = symbols
        self.window = window
        # Store (sequence_idx, price) tuples for each symbol
        self.price_hist: Dict[str, deque] = {s: deque(maxlen=window + 1) for s in symbols}

    def update(self, symbol: str, mid_px: float, timestamp_ns: Optional[int] = None):
        """
        Update price history for a symbol. Maintains rolling window of prices for return calculation.
        """
        if symbol not in self.symbols or np.isnan(mid_px) or mid_px <= 0:
            return

        self.price_hist[symbol].append(mid_px)

    def _calculate_returns(self, symbol: str) -> Optional[np.ndarray]:
        """Calculate log returns for a symbol's price window."""
        prices = list(self.price_hist[symbol])
        if len(prices) < 2:
            return None

        # Log returns over consecutive prices
        prices_arr = np.array(prices)
        rets = np.log(prices_arr[1:] / prices_arr[:-1])

        # Handle edge cases
        rets = np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)

        return rets

    def covariance_matrix(self) -> np.ndarray:
        """
        Compute covariance matrix from recent returns across all symbols.
        Returns square matrix of shape (n_symbols, n_symbols).
        """
        if not all(len(self.price_hist[s]) >= 2 for s in self.symbols):
            # Return identity matrix as fallback
            return np.eye(len(self.symbols))

        returns = []
        for symbol in self.symbols:
            rets = self._calculate_returns(symbol)
            if rets is None:
                # Fallback for missing data
                rets = np.zeros(1)
            returns.append(rets)

        # Align to minimum length (handle different start times)
        min_len = min(len(r) for r in returns if r is not None)
        if min_len < 2:
            return np.eye(len(self.symbols))

        aligned_returns = np.array([r[-min_len:] for r in returns])

        try:
            cov_matrix = np.cov(aligned_returns)
            # Ensure positive semi-definite via eigenvalue clipping
            eigvals, eigvecs = np.linalg.eigh(cov_matrix)
            eigvals_clipped = np.maximum(eigvals, 1e-8)  # Small positive minimum
            cov_matrix = eigvecs @ np.diag(eigvals_clipped) @ eigvecs.T

            return cov_matrix
        except (np.linalg.LinAlgError, ValueError):
            # Fallback to diagonal matrix
            return np.eye(len(self.symbols)) * 1e-6

    def correlation_matrix(self) -> np.ndarray:
        """
        Compute correlation matrix from covariance.
        Returns correlation matrix (diagonal elements = 1).
        """
        cov = self.covariance_matrix()
        std = np.sqrt(np.diag(cov))

        # Avoid division by zero
        mask = std > 0
        corr = np.eye(len(self.symbols))
        corr[np.ix_(mask, mask)] = cov[np.ix_(mask, mask)] / np.outer(std[mask], std[mask])

        # Clip to valid correlation range [-1, 1]
        corr = np.clip(corr, -1, 1)

        return corr

    def get_latest_returns(self) -> Dict[str, float]:
        """Get the most recent return for each symbol."""
        returns = {}
        for symbol in self.symbols:
            rets = self._calculate_returns(symbol)
            if rets is not None and len(rets) > 0:
                returns[symbol] = float(rets[-1])
            else:
                returns[symbol] = 0.0
        return returns

    def is_ready(self) -> bool:
        """Check if tracker has sufficient data for reliable covariance estimates."""
        return all(len(self.price_hist[s]) >= self.window // 3 for s in self.symbols)

    def get_pairwise_correlation(self, symbol1: str, symbol2: str) -> float:
        """Get correlation coefficient between two specific symbols."""
        if symbol1 not in self.symbols or symbol2 not in self.symbols:
            return 0.0

        idx1 = self.symbols.index(symbol1)
        idx2 = self.symbols.index(symbol2)

        corr_matrix = self.correlation_matrix()
        return float(corr_matrix[idx1, idx2])

    def get_realized_volatility(self) -> Dict[str, float]:
        """Get annualized realized volatility for each symbol."""
        vol = {}
        for symbol in self.symbols:
            rets = self._calculate_returns(symbol)
            if rets is not None and len(rets) > 0:
                # Realized vol (annualized approximately, depending on data frequency)
                vol[symbol] = float(np.std(rets) * np.sqrt(252 * 60 * 60))  # Assumes 1-second data
            else:
                vol[symbol] = 0.0
        return vol
