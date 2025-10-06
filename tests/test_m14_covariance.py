#!/usr/bin/env python3
# tests/test_m14_covariance.py — M14: Cross-symbol covariance risk control tests
import numpy as np
import pytest
from strategies.hmm_policy.risk_covariance import CovarianceTracker
from strategies.hmm_policy.portfolio_risk import PortfolioRiskManager, CorrelationRegime, RiskMetrics

def test_covariance_tracker_basic():
    """Test basic covariance tracking functionality."""
    tracker = CovarianceTracker(["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"], window=300)

    # Add some price data
    prices_btc = [50000, 50100, 49900, 50200, 49800]
    prices_eth = [3000, 3010, 2990, 3020, 2980]

    for btc, eth in zip(prices_btc, prices_eth):
        tracker.update("BTCUSDT.BINANCE", btc)
        tracker.update("ETHUSDT.BINANCE", eth)

    assert tracker.is_ready()
    assert len(tracker.price_hist["BTCUSDT.BINANCE"]) == 5
    assert len(tracker.price_hist["ETHUSDT.BINANCE"]) == 5

def test_covariance_matrix():
    """Test covariance matrix calculation."""
    tracker = CovarianceTracker(["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"], window=100)

    # Create correlated returns
    np.random.seed(42)
    n_points = 150
    btc_returns = np.random.normal(0, 0.01, n_points)
    eth_returns = 0.3 * btc_returns + np.random.normal(0, 0.008, n_points)

    # Convert to prices
    btc_prices = 50000 * np.exp(np.cumsum(btc_returns))
    eth_prices = 3000 * np.exp(np.cumsum(eth_returns))

    for btc, eth in zip(btc_prices[:100], eth_prices[:100]):
        tracker.update("BTCUSDT.BINANCE", float(btc))
        tracker.update("ETHUSDT.BINANCE", float(eth))

    cov_matrix = tracker.covariance_matrix()
    assert cov_matrix.shape == (2, 2)
    assert cov_matrix[0, 0] > 0  # BTC variance should be positive
    assert cov_matrix[1, 1] > 0  # ETH variance should be positive
    assert cov_matrix[0, 1] > 0  # Should have positive covariance

def test_correlation_matrix():
    """Test correlation matrix calculation."""
    tracker = CovarianceTracker(["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"], window=100)

    # Perfectly correlated prices (correlation should be 1)
    btc_prices = [50000, 51000, 49000, 52000]
    eth_prices = [3000, 3060, 2940, 3120]  # Perfectly correlated

    for btc, eth in zip(btc_prices, eth_prices):
        tracker.update("BTCUSDT.BINANCE", btc)
        tracker.update("ETHUSDT.BINANCE", eth)

    corr_matrix = tracker.correlation_matrix()
    assert corr_matrix.shape == (2, 2)
    assert abs(corr_matrix[0, 1] - 1.0) < 0.1  # Should be nearly perfectly correlated
    assert abs(corr_matrix[0, 0] - 1.0) < 1e-6  # Diagonal should be 1
    assert abs(corr_matrix[1, 1] - 1.0) < 1e-6

def test_pairwise_correlation():
    """Test getting correlation between specific symbol pairs."""
    tracker = CovarianceTracker(["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"], window=100)

    # Add identical prices (perfect correlation)
    prices = [50000, 50100, 49900, 50200, 49800]
    for price in prices:
        tracker.update("BTCUSDT.BINANCE", price)
        tracker.update("ETHUSDT.BINANCE", price)

    corr = tracker.get_pairwise_correlation("BTCUSDT.BINANCE", "ETHUSDT.BINANCE")
    assert abs(corr - 1.0) < 0.1

    # Test invalid pairs
    assert tracker.get_pairwise_correlation("INVALID", "BTCUSDT.BINANCE") == 0.0

def test_portfolio_risk_manager():
    """Test portfolio risk adjustment functionality."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    manager = PortfolioRiskManager(symbols, target_vol=0.02)

    # Mock covariance matrix (high correlation case)
    cov_matrix = np.array([
        [0.0004, 0.0003],  # BTC variance 0.04%, covar 0.03%
        [0.0003, 0.00025]  # ETH variance 0.025%
    ])

    # Desired positions
    desired_qtys = np.array([0.01, 0.005])  # Both long
    mid_prices = np.array([50000, 3000])

    adjusted_qtys, port_vol, scale, regime = manager.adjust_positions(
        desired_qtys, mid_prices, cov_matrix
    )

    assert len(adjusted_qtys) == 2
    assert port_vol >= 0
    assert 0 < scale <= 1  # Should scale down for high correlation regime
    assert regime in ["lockstep", "normal", "divergent"]

def test_correlation_regimes():
    """Test correlation regime detection."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    manager = PortfolioRiskManager(symbols, max_corr=0.85, min_corr=0.3)

    # Lockstep regime (> 0.85 correlation)
    lockstep_matrix = np.eye(2)
    lockstep_matrix[0, 1] = lockstep_matrix[1, 0] = 0.95

    regime = manager.correlation_regime(lockstep_matrix)
    assert regime == "lockstep"

    # Divergent regime (< 0.3 correlation)
    divergent_matrix = np.eye(2)
    divergent_matrix[0, 1] = divergent_matrix[1, 0] = 0.15

    regime = manager.correlation_regime(divergent_matrix)
    assert regime == "divergent"

    # Normal regime
    normal_matrix = np.eye(2)
    normal_matrix[0, 1] = normal_matrix[1, 0] = 0.5

    regime = manager.correlation_regime(normal_matrix)
    assert regime == "normal"

def test_risk_metrics_computation():
    """Test risk metrics calculation."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    manager = PortfolioRiskManager(symbols)

    # Simple covariance matrix
    cov_matrix = np.array([
        [0.001, 0.0005],
        [0.0005, 0.0008]
    ])

    qtys = np.array([0.01, 0.005])

    metrics = manager.compute_risk_metrics(qtys, cov_matrix)

    assert isinstance(metrics, RiskMetrics)
    assert "corr_btc_eth" in metrics.__dict__
    assert "port_vol" in metrics.__dict__
    assert metrics.corr_regime in ["lockstep", "normal", "divergent"]
    assert all(vol >= 0 for vol in metrics.individual_vols.values())

def test_position_limits():
    """Test that position limits are enforced."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    manager = PortfolioRiskManager(symbols, target_vol=0.02)

    # Try positions way above limits
    large_qtys = np.array([10.0, 5.0])  # Should be clamped to [1.0, 1.0]
    mid_prices = np.array([50000, 3000])
    cov_matrix = np.eye(2) * 0.001

    adjusted_qtys, _, _, _ = manager.adjust_positions(large_qtys, mid_prices, cov_matrix)

    assert np.all(np.abs(adjusted_qtys) <= manager.max_position)
    assert np.all(adjusted_qtys >= manager.min_position)

def test_covariance_edge_cases():
    """Test covariance tracker edge cases."""
    tracker = CovarianceTracker(["BTCUSDT.BINANCE"], window=300)

    # Empty tracker should return identity matrix
    cov = tracker.covariance_matrix()
    assert np.array_equal(cov, np.eye(1))

    # Add some data but not enough for covariance
    tracker.update("BTCUSDT.BINANCE", 50000)
    cov = tracker.covariance_matrix()
    assert cov.shape == (1, 1)

    # Test invalid price handling
    tracker.update("BTCUSDT.BINANCE", 0)  # Invalid price
    tracker.update("BTCUSDT.BINANCE", float('inf'))  # Invalid price
    tracker.update("BTCUSDT.BINANCE", 50000)  # Valid price

    # Should not crash and handle gracefully
    cov = tracker.covariance_matrix()
    assert cov.shape == (1, 1)
