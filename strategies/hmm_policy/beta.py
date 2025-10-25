#!/usr/bin/env python3
# strategies/hmm_policy/beta.py — M14.1: Beta calculation and hedging utilities
import numpy as np
from typing import List, Tuple, Optional

def beta_to_leader(returns_matrix: np.ndarray, leader_idx: int) -> float:
    """
    Calculate beta of a symbol vs. a cluster leader.

    Args:
        returns_matrix: Shape (n_periods, n_symbols) of returns
        leader_idx: Column index of cluster leader

    Returns:
        Beta coefficient (how much symbol moves vs. leader)
    """
    if returns_matrix.shape[1] <= leader_idx or returns_matrix.shape[0] < 5:
        return 1.0  # Default beta = 1 (perfect correlation)

    # Get leader returns as X (independent)
    y_leader = returns_matrix[:, leader_idx:leader_idx + 1]

    # For each other symbol, compute beta vs leader
    # Simple OLS: returns ~ intercept + beta * leader_returns
    try:
        # X = leader returns, y = symbol returns, but we only return beta
        A = np.column_stack([np.ones(returns_matrix.shape[0]), y_leader.ravel()])
        beta = np.linalg.lstsq(A, returns_matrix[:, :], rcond=None)[0][1]
        return float(beta[0])  # Return beta for first symbol (could generalize)
    except (np.linalg.LinAlgError, ValueError):
        return 1.0

def compute_beta_matrix(returns_matrix: np.ndarray, cluster_assignments: np.ndarray) -> np.ndarray:
    """
    Compute beta of each symbol vs. its cluster leader.

    Args:
        returns_matrix: Shape (n_periods, n_symbols)
        cluster_assignments: Cluster for each symbol

    Returns:
        Beta matrix of shape (n_symbols,)
    """
    n_symbols = returns_matrix.shape[1]
    betas = np.ones(n_symbols)  # Default betas = 1

    if returns_matrix.shape[0] < 5:
        return betas

    # For each cluster, find leader (symbol with median volatility) and compute betas
    unique_clusters = np.unique(cluster_assignments)
    for cluster in unique_clusters:
        cluster_mask = cluster_assignments == cluster
        cluster_indices = np.where(cluster_mask)[0]

        if len(cluster_indices) < 2:
            continue  # Need at least 2 for beta

        # Find leader: symbol with median volatility in cluster
        cluster_returns = returns_matrix[:, cluster_indices]
        cluster_vols = np.std(cluster_returns, axis=0)
        leader_idx_local = np.argsort(cluster_vols)[len(cluster_vols) // 2]  # Median vol
        leader_idx_global = cluster_indices[leader_idx_local]

        # Compute all betas in cluster vs. leader
        try:
            y_leader = returns_matrix[:, leader_idx_global]
            A = np.column_stack([np.ones(returns_matrix.shape[0]), y_leader])

            for i, sym_idx in enumerate(cluster_indices):
                if sym_idx != leader_idx_global:  # Skip leader itself
                    y_symbol = returns_matrix[:, sym_idx]
                    coeffs = np.linalg.lstsq(A, y_symbol, rcond=None)[0]
                    betas[sym_idx] = float(coeffs[1])  # Beta coefficient

        except (np.linalg.LinAlgError, ValueError):
            pass

    return betas

def hedged_position_size(desired_qty: float, beta: float, hedging_target: float = 0.0) -> Tuple[float, float]:
    """
    Calculate hedged position size given beta and target beta.

    Args:
        desired_qty: Original position size
        beta: Calculated beta vs. hedging instrument
        hedging_target: Target beta after hedging (0 = neutralize, etc.)

    Returns:
        Tuple of (hedged_qty, hedge_qty_needed)
    """
    if abs(beta) < 0.1:
        return desired_qty, 0.0  # Too low correlation for effective hedging

    # Simple beta hedge: position + hedge_ratio * position
    # to achieve target_beta = original_beta / (1 + hedge_ratio)
    if beta != 1.0:
        hedge_ratio = (beta - hedging_target) / (beta - (-hedging_target))
        # We want target_beta = 0, so hedge_ratio = -beta / (1 - beta) but simplify
        hedge_ratio = -beta / (1 - beta)
        # Bound reasonable hedge ratios
        hedge_ratio = np.clip(hedge_ratio, -2.0, 2.0)

        hedge_qty = hedge_ratio * desired_qty
        hedged_qty = desired_qty + hedge_qty

        return hedged_qty, hedge_qty
    else:
        return desired_qty, 0.0  # Perfect correlation, can't hedge

def detect_hedging_opportunity(beta: float, correlation_regime: str) -> bool:
    """
    Determine if beta hedging makes sense given correlation regime.

    Returns:
        True if hedging should be considered
    """
    # In lockstep regimes, betas are likely unreliable (everything moves together)
    if correlation_regime == "lockstep":
        return False

    # Otherwise, consider if beta is significantly different from 1
    return abs(beta - 1.0) > 0.4  # Only hedge if substantially different

def cluster_beta_risk(beta_vector: np.ndarray, cluster_assignments: np.ndarray) -> dict:
    """
    Assess beta risk at cluster level.

    Returns:
        Dict with cluster-level beta statistics
    """

    unique_clusters = np.unique(cluster_assignments)
    cluster_stats = {}

    for cluster in unique_clusters:
        cluster_mask = cluster_assignments == cluster
        cluster_betas = beta_vector[cluster_mask]

        if len(cluster_betas) > 1:
            cluster_stats[f"cluster_{cluster}"] = {
                "mean_beta": float(np.mean(cluster_betas)),
                "std_beta": float(np.std(cluster_betas)),
                "beta_range": float(np.ptp(cluster_betas)),  # Range
                "needs_hedging": bool(np.any(np.abs(cluster_betas - 1.0) > 0.5))
            }

    return cluster_stats
