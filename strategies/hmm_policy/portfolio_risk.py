#!/usr/bin/env python3
# strategies/hmm_policy/portfolio_risk.py — M14: Correlation-aware portfolio exposure scaling
import numpy as np
from typing import Dict, List, Tuple, Optional, Literal
from typing import Literal
from dataclasses import dataclass

CorrelationRegime = Literal["lockstep", "normal", "divergent"]

@dataclass
class RiskMetrics:
    corr_btc_eth: float
    port_vol: float
    corr_regime: CorrelationRegime
    exposure_scale: float
    individual_vols: Dict[str, float]

class PortfolioRiskManager:
    """
    Manages portfolio-level risk by adjusting exposure based on cross-symbol correlations.
    Automatically scales positions when markets move in lockstep vs. diverge.
    """

    def __init__(self, symbols: List[str], target_vol: float = 0.02, max_corr: float = 0.85, min_corr: float = 0.3):
        """
        Initialize with risk parameters.

        Args:
            symbols: List of symbol names (e.g., ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"])
            target_vol: Target portfolio volatility (annualized)
            max_corr: Correlation threshold for "lockstep" regime
            min_corr: Correlation threshold for "divergent" regime
        """
        self.symbols = symbols
        self.target_vol = target_vol
        self.max_corr = max_corr
        self.min_corr = min_corr
        self.last_regime = "normal"

        # Risk limits per regime
        self.regime_limits = {
            "lockstep": 0.75,    # Compress exposure during high correlation
            "normal": 1.0,       # Full exposure in normal correlation
            "divergent": 1.25    # Allow higher exposure when uncorrelated
        }

        # Position limits
        self.max_position = 1.0    # Max position per symbol
        self.min_position = -1.0   # Min position per symbol

    def correlation_regime(self, corr_matrix: np.ndarray) -> CorrelationRegime:
        """
        Determine correlation regime from matrix.
        For now, focuses on BTC-ETH pairwise correlation.
        """
        if corr_matrix.shape[0] < 2:
            return "normal"

        # Use BTC-ETH correlation as primary driver
        corr_btc_eth = corr_matrix[0, 1] if corr_matrix.shape[0] > 1 else 0.0

        if abs(corr_btc_eth) > self.max_corr:
            regime = "lockstep"
        elif abs(corr_btc_eth) < self.min_corr:
            regime = "divergent"
        else:
            regime = "normal"

        self.last_regime = regime
        return regime

    def adjust_positions(
        self,
        desired_qtys: np.ndarray,
        mid_prices: np.ndarray,
        cov_matrix: np.ndarray,
        current_exposure: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, float, float, CorrelationRegime]:
        """
        Adjust position quantities based on portfolio risk targets.

        Args:
            desired_qtys: Desired position sizes from strategies
            mid_prices: Current mid prices for each symbol
            cov_matrix: Covariance matrix from CovarianceTracker
            current_exposure: Current actual positions (for weighting)

        Returns:
            Tuple of (adjusted_qtys, port_vol, exposure_scale, corr_regime)
        """
        if len(desired_qtys) != len(mid_prices) or len(desired_qtys) != cov_matrix.shape[0]:
            raise ValueError("Inconsistent dimensions in risk adjustment")

        if np.any(~np.isfinite(desired_qtys)) or np.any(~np.isfinite(mid_prices)):
            # Return zero exposure if invalid inputs
            return np.zeros_like(desired_qtys), 0.0, 0.0, "normal"

        # Calculate current portfolio volatility
        port_vol = self._calculate_portfolio_volatility(desired_qtys, cov_matrix)

        # Determine correlation regime
        corr_matrix = self._cov_to_corr(cov_matrix)
        regime = self.correlation_regime(corr_matrix)

        # Apply regime-based scaling
        regime_scale = self.regime_limits.get(regime, 1.0)

        # Scale to target volatility (but respect regime limits)
        vol_scale = 1.0
        if port_vol > 0:
            vol_scale = min(regime_scale, self.target_vol / port_vol)
        else:
            vol_scale = regime_scale

        # Apply scaling to desired positions
        adjusted_qtys = desired_qtys * vol_scale

        # Apply position limits
        adjusted_qtys = np.clip(adjusted_qtys, self.min_position, self.max_position)

        # Recalculate resulting portfolio volatility
        final_port_vol = self._calculate_portfolio_volatility(adjusted_qtys, cov_matrix)

        return adjusted_qtys, final_port_vol, vol_scale, regime

    def _calculate_portfolio_volatility(self, qtys: np.ndarray, cov_matrix: np.ndarray) -> float:
        """Calculate portfolio volatility from positions and covariance."""
        try:
            port_var = np.dot(qtys, np.dot(cov_matrix, qtys))
            return max(0.0, float(np.sqrt(port_var)))
        except (ValueError, np.linalg.LinAlgError):
            return 0.0

    def _cov_to_corr(self, cov_matrix: np.ndarray) -> np.ndarray:
        """Convert covariance matrix to correlation matrix."""
        std = np.sqrt(np.diag(cov_matrix))
        std_matrix = np.outer(std, std)

        # Avoid division by zero
        mask = std_matrix > 0
        corr = np.eye(cov_matrix.shape[0])
        corr[mask] = cov_matrix[mask] / std_matrix[mask]

        return np.clip(corr, -1, 1)

    def compute_risk_metrics(self, qtys: np.ndarray, cov_matrix: np.ndarray) -> RiskMetrics:
        """
        Compute comprehensive risk metrics for monitoring and logging.
        """
        individual_vols = {}
        symbols_short = [s.split('.')[0] for s in self.symbols]  # BTC, ETH, etc.

        for i, symbol in enumerate(self.symbols):
            try:
                vol = np.sqrt(cov_matrix[i, i])
                individual_vols[symbol] = float(vol)
            except (IndexError, ValueError):
                individual_vols[symbol] = 0.0

        corr_matrix = self._cov_to_corr(cov_matrix)
        port_vol = self._calculate_portfolio_volatility(qtys, cov_matrix)

        # Get BTC-ETH correlation if available
        corr_btc_eth = float(corr_matrix[0, 1]) if corr_matrix.shape[0] > 1 else 0.0
        corr_regime = self.correlation_regime(corr_matrix)

        # Exposure scale represents how much we scaled from target positions
        exposure_scale = 1.0  # Placeholder - would need original positions passed in

        return RiskMetrics(
            corr_btc_eth=corr_btc_eth,
            port_vol=port_vol,
            corr_regime=corr_regime,
            exposure_scale=exposure_scale,
            individual_vols=individual_vols
        )

    def get_target_volatility(self, regime: Optional[CorrelationRegime] = None) -> float:
        """Get target volatility for a given regime."""
        if regime is None:
            regime = self.last_regime
        regime_scale = self.regime_limits.get(regime, 1.0)
        return self.target_vol * regime_scale

    def should_rebalance_positions(self) -> bool:
        """
        Determine if positions should be rebalanced based on regime changes.
        Called after regime transitions to decide if risk recalculation needed.
        """
        # Simple implementation: rebalance on regime change
        # Could be enhanced with thresholds, timing, etc.
        return True  # For now, always allow rebalancing
