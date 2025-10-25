#!/usr/bin/env python3
# strategies/hmm_policy/corr_windows.py — M14.1: Multi-window correlation blending
import numpy as np
from collections import deque
from typing import List, Optional, Dict

class MultiWindowCorr:
    """
    Adaptive correlation tracking with short and long windows blended via lambda.
    Weights short-term correlations more during volatility, stable during calm.
    """

    def __init__(self, symbols: List[str], short_window: int = 120, long_window: int = 1200):
        """
        Initialize windows for log-return correlation tracking.

        Args:
            symbols: List of symbol names
            short_window: Short timescale (ticks), ~2min for fast changes
            long_window: Long timescale (ticks), ~20min for stability
        """
        self.symbols = symbols
        self.n_symbols = len(symbols)
        self.short_window = short_window
        self.long_window = long_window

        # Price history deques: maxlen +1 for return calculation
        self.short_prices = {s: deque(maxlen=short_window + 1) for s in symbols}
        self.long_prices = {s: deque(maxlen=long_window + 1) for s in symbols}

        # Market regimes for lambda adaptation
        self.market_vol_threshold = 0.01  # 1% per tick as calm/volatile boundary

    def update(self, symbol: str, mid: float, timestamp_ns: Optional[int] = None):
        """
        Update price history for a symbol.

        Args:
            symbol: Symbol name
            mid: Mid-price
            timestamp_ns: UTC timestamp when price was observed
        """
        if symbol not in self.symbols or np.isnan(mid) or mid <= 0:
            return

        # Update both windows
        self.short_prices[symbol].append(mid)
        self.long_prices[symbol].append(mid)

    def _compute_returns(self, price_deque: deque) -> Optional[np.ndarray]:
        """
        Compute log returns from price series.

        Args:
            price_deque: Deque of consecutive prices

        Returns:
            Array of log returns, or None if insufficient data
        """
        prices = np.array(price_deque)
        if len(prices) < 3:
            return None

        # Log returns: log(p_{t}) - log(p_{t-1})
        log_prices = np.log(prices)
        returns = np.diff(log_prices)

        # Clean edge cases
        returns = np.clip(returns, -0.5, 0.5)  # Cap at reasonable moves
        returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)

        return returns

    def _compute_correlation_matrix(self, price_histories: Dict[str, deque]) -> np.ndarray:
        """
        Compute correlation matrix from price histories for one window.

        Args:
            price_histories: Dict of symbol -> deque of prices

        Returns:
            Correlation matrix of shape (n_symbols, n_symbols)
        """
        n = self.n_symbols
        corr_matrix = np.eye(n)  # Diagonal = 1

        if not self._ready_check(price_histories):
            return corr_matrix

        # Build return matrix
        return_matrix = []
        valid_symbols = []

        for symbol in self.symbols:
            rets = self._compute_returns(price_histories[symbol])
            if rets is not None and len(rets) > 5:  # Minimum sample size
                return_matrix.append(rets)
                valid_symbols.append(symbol)

        if len(valid_symbols) < 2:
            return corr_matrix

        return_matrix = np.array(return_matrix)

        # Compute correlations for each pair
        for i, sym_i in enumerate(valid_symbols):
            for j, sym_j in enumerate(valid_symbols[i+1:], i+1):  # Upper triangle only
                if i < len(return_matrix) and j < len(return_matrix):
                    idx_i = self.symbols.index(sym_i)
                    idx_j = self.symbols.index(sym_j)

                    # Align windows to common length
                    ret_i = return_matrix[i]
                    ret_j = return_matrix[j]
                    min_len = min(len(ret_i), len(ret_j))

                    if min_len >= 2:
                        try:
                            rho = np.corrcoef(ret_i[-min_len:], ret_j[-min_len:])[0, 1]
                            rho = np.clip(rho, -1.0, 1.0)

                            if not np.isnan(rho):
                                corr_matrix[idx_i, idx_j] = rho
                                corr_matrix[idx_j, idx_i] = rho
                        except (ValueError, ZeroDivisionError):
                            continue

        return corr_matrix

    def _ready_check(self, price_histories: Dict[str, deque]) -> bool:
        """Check if sufficient data exists across symbols."""
        ready_count = sum(1 for s in self.symbols if len(price_histories[s]) >= 3)
        return ready_count >= 2  # At least 2 symbols with data

    def short_corr_matrix(self) -> np.ndarray:
        """Compute short-window correlation matrix."""
        return self._compute_correlation_matrix(self.short_prices)

    def long_corr_matrix(self) -> np.ndarray:
        """Compute long-window correlation matrix."""
        return self._compute_correlation_matrix(self.long_prices)

    def blended_corr_matrix(self, lam: float = 0.6) -> np.ndarray:
        """
        Compute blended correlation matrix using λ for short/long weighting.

        Args:
            lam: Weight for short window (0.0 = all long, 1.0 = all short)

        Returns:
            Blended correlation matrix
        """
        lam = np.clip(lam, 0.0, 1.0)

        short_corr = self.short_corr_matrix()
        long_corr = self.long_corr_matrix()

        # Blend matrices
        blended = lam * short_corr + (1.0 - lam) * long_corr

        # Ensure diagonal = 1 and proper bounds
        np.fill_diagonal(blended, 1.0)
        blended = np.clip(blended, -1.0, 1.0)

        return blended

    def adaptive_lambda(self, realized_vol: Optional[float] = None) -> float:
        """
        Adapt lambda based on market conditions.
        Higher volatility → more weight on short window.

        Args:
            realized_vol: Realized volatility estimate

        Returns:
            Adaptive lambda value (0.0 to 1.0)
        """
        if realized_vol is None or realized_vol <= 0:
            return 0.4  # Default: slightly favor stable long-term relationships

        # Map volatility to lambda via sigmoid
        # High vol → lambda=1.0 (short-term dominant)
        # Low vol → lambda=0.0 (long-term dominant)
        vol_norm = realized_vol / self.market_vol_threshold
        lambda_val = 1.0 / (1.0 + np.exp(-2.0 * (vol_norm - 1.0)))  # Sigmoid centered at vol_threshold

        return float(np.clip(lambda_val, 0.1, 0.9))  # Keep reasonable bounds

    def get_latest_volatility(self) -> float:
        """
        Estimate realized volatility from short window across all symbols.

        Returns:
            Average realized volatility across symbols
        """
        volatility = []

        for symbol in self.symbols:
            rets = self._compute_returns(self.short_prices[symbol])
            if rets is not None and len(rets) > 0:
                vol = float(np.std(rets))
                if vol > 0:
                    volatility.append(vol)

        return np.mean(volatility) if volatility else 0.0

    def get_pairwise_corrs(self, lam: float = 0.6) -> Dict[str, Dict[str, float]]:
        """
        Get comprehensive pairwise correlations as dict.

        Returns:
            Nested dict: {symbol1: {symbol2: correlation, ...}, ...}
        """
        corr_matrix = self.blended_corr_matrix(lam)
        correlations = {}

        for i, sym_i in enumerate(self.symbols):
            correlations[sym_i] = {}
            for j, sym_j in enumerate(self.symbols):
                correlations[sym_i][sym_j] = float(corr_matrix[i, j])

        return correlations

    def correlation_entropy(self, lam: float = 0.6) -> float:
        """
        Compute correlation matrix entropy.
        Lower entropy = correlations concentrated (riskier structure).

        Returns:
            Entropy of correlation distribution
        """
        corr_matrix = self.blended_corr_matrix(lam)

        # Use absolute correlations for entropy (focus on strength)
        abs_corr = np.abs(corr_matrix)

        # Flatten upper triangle
        iu = np.triu_indices_from(abs_corr, k=1)
        corr_values = abs_corr[iu]

        if len(corr_values) == 0:
            return 0.0

        # Normalize to probability distribution
        corr_norm = corr_values / np.sum(corr_values)

        # Compute entropy
        entropy = 0.0
        for p in corr_norm:
            if p > 0:
                entropy -= p * np.log(p)

        return max(0.0, float(entropy))
