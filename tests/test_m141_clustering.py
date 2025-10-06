#!/usr/bin/env python3
# tests/test_m141_clustering.py — M14.1: Adaptive correlation clustering tests
import numpy as np
import pytest
from strategies.hmm_policy.corr_windows import MultiWindowCorr
from strategies.hmm_policy.corr_cluster import CorrClusterer
from strategies.hmm_policy.cluster_risk import ClusterRiskAllocator
from strategies.hmm_policy.beta import compute_beta_matrix, detect_hedging_opportunity

def test_multiwindow_corr_basic():
    """Test basic MultiWindowCorr functionality."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    corr = MultiWindowCorr(symbols)

    # Add some price data
    prices_btc = [50000, 50100, 49900, 50200, 49800]
    prices_eth = [3000, 3010, 2990, 3020, 2980]

    for btc, eth in zip(prices_btc, prices_eth):
        corr.update("BTCUSDT.BINANCE", btc)
        corr.update("ETHUSDT.BINANCE", eth)

    # Short window should have less stable correlations
    short_corr = corr.short_corr_matrix()
    assert short_corr.shape == (2, 2)
    assert np.allclose(short_corr, short_corr.T, atol=1e-10)  # Must be symmetric

def test_blended_correlation():
    """Test weighted correlation blending."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    corr = MultiWindowCorr(symbols, short_window=100, long_window=200)

    # Add extended data to populate both windows
    n_points = 150
    np.random.seed(42)
    btc_returns = np.random.normal(0, 0.01, n_points)
    eth_returns = 0.7 * btc_returns + np.random.normal(0, 0.005, n_points)

    btc_prices = 50000 * np.exp(np.cumsum(btc_returns))
    eth_prices = 3000 * np.exp(np.cumsum(eth_returns))

    for btc, eth in zip(btc_prices, eth_prices):
        corr.update("BTCUSDT.BINANCE", float(btc))
        corr.update("ETHUSDT.BINANCE", float(eth))

    # Test lambda blending
    lam_short = corr.blended_corr_matrix(lam=1.0)  # All short
    lam_long = corr.blended_corr_matrix(lam=0.0)   # All long
    lam_blended = corr.blended_corr_matrix(lam=0.5)  # 50/50

    assert lam_short.shape == (2, 2)
    assert lam_long.shape == (2, 2)
    assert lam_blended.shape == (2, 2)

    # BTC-ETH correlation should be high (around 0.7-0.8 given cross-correlation)
    assert lam_blended[0, 1] > 0.5

def test_adaptive_lambda():
    """Test lambda adaptation based on volatility."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    corr = MultiWindowCorr(symbols)

    # Low volatility phase
    low_vol_rep = corr.adaptive_lambda(realized_vol=0.005)  # 0.5% per tick
    high_vol_rep = corr.adaptive_lambda(realized_vol=0.02)  # 2% per tick

    # High vol should favor short-term (lambda > 0.5)
    # Low vol should favor long-term (lambda < 0.5)
    assert high_vol_rep > 0.5
    assert low_vol_rep < 0.5

def test_correlation_entropy():
    """Test correlation entropy calculations."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    corr = MultiWindowCorr(symbols)

    # Populate with correlated data
    n_points = 100
    btc_prices = [50000 + 10 * np.sin(2*np.pi*i/20) for i in range(n_points)]
    eth_prices = [3000 + 10 * np.sin(2*np.pi*i/20 + np.pi/6) for i in range(n_points)]

    for btc, eth in zip(btc_prices, eth_prices):
        corr.update("BTCUSDT.BINANCE", btc)
        corr.update("ETHUSDT.BINANCE", eth)

    entropy = corr.correlation_entropy()
    assert isinstance(entropy, float)
    assert entropy >= 0

    # Get pairwise correlations
    corr_dict = corr.get_pairwise_corrs()
    assert "BTCUSDT.BINANCE" in corr_dict
    assert "ETHUSDT.BINANCE" in corr_dict

def test_corr_clustering():
    """Test correlation-based clustering."""
    clusterer = CorrClusterer(n_clusters_range=(1, 3), random_state=42)

    # Create correlation matrix that suggests 2 clusters
    corr_matrix = np.array([
        [1.0, 0.8, 0.85, 0.2, 0.15],  # Symbol 0 correlated with 1,2 but not 3,4
        [0.8, 1.0, 0.9, 0.25, 0.1],   # Symbol 1 correlated with 0,2 but not 3,4
        [0.85, 0.9, 1.0, 0.3, 0.15],  # Symbol 2 in first cluster
        [0.2, 0.25, 0.3, 1.0, 0.9],   # Symbol 3 correlated with 4
        [0.15, 0.1, 0.15, 0.9, 1.0]   # Symbol 4 in second cluster
    ])

    # Normalize to proper correlation matrix
    std = np.ones(5)  # Identity correlation with above off-diagonals
    corr_matrix = corr_matrix if np.all(np.abs(corr_matrix) <= 1.0) else np.eye(5)

    labels = clusterer.fit(corr_matrix)

    assert len(labels) == 5
    assert clusterer.n_clusters >= 1 and clusterer.n_clusters <= 3

    # Test cluster membership
    memberships = clusterer.get_cluster_membership()
    assert len(memberships) >= 1

    # Test cluster stats
    stats = clusterer.get_cluster_stats()
    assert "n_clusters" in stats
    assert "stability_score" in stats
    assert "avg_cluster_size" in stats

def test_cluster_risk_allocation():
    """Test cluster-based risk allocation."""
    symbols = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE", "TOKEN.BINANCE"]
    allocator = ClusterRiskAllocator(symbols, target_port_vol=0.02)

    # Desired positions and covariance
    desired_qtys = np.array([0.01, 0.005, 0.02])
    mid_prices = np.array([50000, 3000, 1.5])

    # Example covariance matrix (moderate correlations)
    cov_matrix = np.array([
        [0.001, 0.0005, 0.0002],  # BTC variance high
        [0.0005, 0.0008, 0.0001],  # ETH moderate
        [0.0002, 0.0001, 0.0001]   # TOKEN low variance
    ])

    # Cluster assignments (BTC and ETH together, TOKEN separate)
    cluster_labels = np.array([0, 0, 1])

    adjusted_qtys, port_vol, cluster_weights = allocator.allocate(
        desired_qtys, mid_prices, cov_matrix, cluster_labels
    )

    assert len(adjusted_qtys) == 3
    assert port_vol >= 0
    assert isinstance(cluster_weights, dict)
    assert len(cluster_weights) >= 1

    # Test that allocations scale towards target vol
    assert port_vol < 0.05  # Should be close to target 2%

def test_beta_calculations():
    """Test beta calculation and hedging logic."""
    # Create sample returns matrix
    np.random.seed(42)
    n_periods, n_symbols = 50, 3
    returns_matrix = np.random.normal(0, 0.01, (n_periods, n_symbols))

    # Make symbols 1 and 2 highly correlated with symbol 0 (leader)
    returns_matrix[:, 1] = 0.8 * returns_matrix[:, 0] + 0.002 * np.random.normal(0, 1, n_periods)
    returns_matrix[:, 2] = 1.2 * returns_matrix[:, 0] + 0.001 * np.random.normal(0, 1, n_periods)

    cluster_assignments = np.array([0, 0, 0])  # All same cluster
    betas = compute_beta_matrix(returns_matrix, cluster_assignments)

    assert len(betas) == 3
    assert np.all(np.isfinite(betas))

    # Symbol 1 should have beta ~0.8, symbol 2 ~1.2, symbol 0 ~1.0 (leader)
    assert abs(betas[1] - 0.8) < 0.3  # Approximate test
    assert abs(betas[2] - 1.2) < 0.5

    # Test hedging opportunity detection
    assert detect_hedging_opportunity(0.6, "normal") == False  # Not different enough from 1
    assert detect_hedging_opportunity(0.4, "normal") == True   # Significantly different
    assert detect_hedging_opportunity(1.5, "lockstep") == False  # Lockstep, skip hedging

def test_cluster_stability():
    """Test cluster stability assessment."""
    from strategies.hmm_policy.cluster_risk import ClusterRiskAllocator

    # Test via ClusterRiskAllocator (which has stability assessment)
    symbols = ["A", "B", "C", "D"]
    allocator = ClusterRiskAllocator(symbols)

    # Add some historical label sequences
    hist_labels = [
        np.array([0, 0, 1, 1]),
        np.array([0, 0, 1, 1]),
        np.array([0, 0, 1, 1]),  # Very stable labels
        np.array([0, 1, 1, 1])   # One switch: symbol 1 moved
    ]

    current_labels = np.array([0, 0, 1, 1])
    stability = allocator.assess_cluster_stability(current_labels, hist_labels)

    assert "stability_score" in stability
    assert "transition_rate" in stability
    assert stability["stability_score"] > 0.5  # Should be fairly stable

    # Test reclustering decision
    should_recluster = allocator.should_recluster(current_labels, hist_labels)
    assert isinstance(should_recluster, bool)

def test_multiwindow_edge_cases():
    """Test edge cases for multi-window correlation."""
    # Single symbol
    corr = MultiWindowCorr(["BTCUSDT.BINANCE"])
    corr.update("BTCUSDT.BINANCE", 50000)

    # Should handle gracefully
    short = corr.short_corr_matrix()
    assert short.shape == (1, 1)
    assert short[0, 0] == 1.0  # Perfect autocorrelation

    # Invalid inputs
    corr.update("INVALID", 50000)  # Should not crash

def test_cluster_allocation_edge_cases():
    """Test edge cases for cluster allocation."""
    symbols = ["BTCUSDT.BINANCE"]
    allocator = ClusterRiskAllocator(symbols)

    # Single symbol allocation
    desired = np.array([0.01])
    prices = np.array([50000])
    cov = np.array([[0.001]])
    labels = np.array([0])

    adjusted, port_vol, weights = allocator.allocate(desired, prices, cov, labels)

    assert len(adjusted) == 1
    assert port_vol > 0
    assert isinstance(weights, dict)

def test_beta_hedged_positions():
    """Test beta-based position hedged positions."""
    from strategies.hmm_policy.beta import hedged_position_size, cluster_beta_risk

    # Test hedging calculation
    desired = 0.01
    beta = 1.5  # More volatile than market

    hedged, hedge_needed = hedged_position_size(desired, beta, hedging_target=1.0)

    assert isinstance(hedged, float)
    assert isinstance(hedge_needed, float)

    # Test cluster beta risk assessment
    betas = np.array([1.0, 1.2, 0.8, 1.5])
    cluster_assignments = np.array([0, 0, 1, 1])

    risk_stats = cluster_beta_risk(betas, cluster_assignments)

    assert len(risk_stats) >= 1
    for cluster_stat in risk_stats.values():
        assert "mean_beta" in cluster_stat
        assert "std_beta" in cluster_stat
