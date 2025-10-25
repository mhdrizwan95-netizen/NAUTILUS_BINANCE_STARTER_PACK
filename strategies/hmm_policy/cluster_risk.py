#!/usr/bin/env python3
# strategies/hmm_policy/cluster_risk.py — M14.1: Equal-risk allocation across correlation clusters
import numpy as np
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

class ClusterRiskAllocator:
    """
    Allocates portfolio risk across correlation clusters using equal risk contribution (ERC).
    Ensures balanced exposure across discovered market regimes.
    """

    def __init__(self, symbols: List[str], day_budget_usd: float = 100.0,
                 target_port_vol: float = 0.02, max_cluster_imbalance: float = 0.5):
        """
        Initialize cluster-based risk allocator.

        Args:
            symbols: List of symbol names
            day_budget_usd: Total daily risk budget
            target_port_vol: Target portfolio volatility (fractional)
            max_cluster_imbalance: Max risk weight difference allowed (for stability)
        """
        self.symbols = symbols
        self.n_symbols = len(symbols)
        self.day_budget_usd = day_budget_usd
        self.target_port_vol = target_port_vol
        self.max_cluster_imbalance = max_cluster_imbalance

    def allocate(self, desired_qtys: np.ndarray, mid_prices: np.ndarray,
                 cov_matrix: np.ndarray, cluster_labels: np.ndarray) -> Tuple[np.ndarray, float, Dict[int, float]]:
        """
        Allocate risk across clusters with equal risk contribution per cluster.

        Args:
            desired_qtys: Original desired position sizes (shape: n_symbols)
            mid_prices: Current mid prices (shape: n_symbols)
            cov_matrix: Covariance matrix (shape: n_symbols x n_symbols)
            cluster_labels: Cluster assignments (shape: n_symbols)

        Returns:
            Tuple of (adjusted_qtys, port_vol, cluster_weights)
                - adjusted_qtys: Final position sizes
                - port_vol: Resulting portfolio volatility
                - cluster_weights: Dict of cluster_id -> risk_weight
        """
        if len(desired_qtys) != self.n_symbols or cov_matrix.shape[0] != self.n_symbols:
            raise ValueError(f"Dimension mismatch: got {len(desired_qtys)}, {cov_matrix.shape}")

        if np.any(~np.isfinite(desired_qtys)) or np.any(desired_qtys == 0):
            return np.zeros(self.n_symbols), 0.0, {}

        # Group symbols by cluster
        clusters = self._group_by_cluster(cluster_labels)
        n_clusters = len(clusters)

        if n_clusters == 0:
            return np.zeros(self.n_symbols), 0.0, {}

        # Step 1: Allocate equal risk weight to each cluster
        equal_weight = 1.0 / n_clusters
        cluster_weights = {cid: equal_weight for cid in clusters.keys()}

        # Step 2: Compute per-cluster risk statistics
        cluster_vols = self._compute_cluster_vols(desired_qtys, cov_matrix, clusters)

        # Step 3: Iterative ERC convergence (simplified)
        cluster_weights = self._balance_cluster_risks(cluster_weights, cluster_vols, desired_qtys, cov_matrix, clusters)

        # Step 4: Apply cluster weights to symbol positions
        adjusted_qtys = self._apply_cluster_weights(desired_qtys, cov_matrix, clusters, cluster_weights)

        # Step 5: Scale to global volatility target
        adjusted_qtys = self._scale_to_target_vol(adjusted_qtys, cov_matrix, self.target_port_vol)

        # Step 6: Calculate final portfolio volatility
        port_vol = self._calculate_portfolio_volatility(adjusted_qtys, cov_matrix)

        return adjusted_qtys, port_vol, cluster_weights

    def _group_by_cluster(self, cluster_labels: np.ndarray) -> Dict[int, List[int]]:
        """
        Group symbol indices by cluster assignment.

        Returns:
            Dict of cluster_id -> list of symbol indices
        """
        clusters = defaultdict(list)
        for i, label in enumerate(cluster_labels):
            clusters[int(label)].append(i)
        return dict(clusters)

    def _compute_cluster_vols(self, qtys: np.ndarray, cov_matrix: np.ndarray,
                             clusters: Dict[int, List[int]]) -> Dict[int, float]:
        """
        Compute volatility contribution for each cluster given current positions.

        Returns:
            Dict of cluster_id -> volatility contribution
        """
        cluster_vols = {}

        for cluster_id, symbol_indices in clusters.items():
            if len(symbol_indices) == 0:
                cluster_vols[cluster_id] = 0.0
                continue

            # Extract cluster covariance submatrix
            Σ_cluster = cov_matrix[np.ix_(symbol_indices, symbol_indices)]
            q_cluster = qtys[symbol_indices]

            # Cluster volatility as sqrt(q' Σ q)
            cluster_vol_sq = q_cluster.T @ Σ_cluster @ q_cluster
            cluster_vols[cluster_id] = max(0.0, float(np.sqrt(cluster_vol_sq)))

        return cluster_vols

    def _balance_cluster_risks(self, cluster_weights: Dict[int, float],
                              cluster_vols: Dict[int, float], qtys: np.ndarray,
                              cov_matrix: np.ndarray, clusters: Dict[int, List[int]],
                              max_iter: int = 3) -> Dict[int, float]:
        """
        Iteratively balance cluster risk contributions toward equality.
        Simplified ERC implementation for clusters.
        """
        if len(cluster_weights) <= 1:
            return cluster_weights

        target_risk = sum(cluster_vols[cid] for cid in cluster_weights.keys())

        for _ in range(max_iter):
            # Compute current risk contributions
            current_risks = {}
            for cid in cluster_weights.keys():
                current_risks[cid] = cluster_weights[cid] * cluster_vols.get(cid, 0)

            # Adjust weights inversely to current risk
            total_risk = sum(current_risks.values())
            if total_risk > 0:
                for cid in cluster_weights.keys():
                    cluster_weights[cid] *= (total_risk / (2 * current_risks[cid]))

                # Normalize weights
                total_weight = sum(cluster_weights.values())
                if total_weight > 0:
                    cluster_weights = {cid: w / total_weight for cid, w in cluster_weights.items()}

        return cluster_weights

    def _apply_cluster_weights(self, qtys: np.ndarray, cov_matrix: np.ndarray,
                              clusters: Dict[int, List[int]], cluster_weights: Dict[int, float]) -> np.ndarray:
        """
        Apply cluster weights to adjust symbol positions within each cluster.
        """
        adjusted_qtys = qtys.copy()

        for cluster_id, symbol_indices in clusters.items():
            if len(symbol_indices) == 0 or cluster_id not in cluster_weights:
                continue

            weight = cluster_weights[cluster_id]

            # Scale all symbols in cluster proportionally
            # Note: This assumes equal weighting within cluster; could be made smarter
            cluster_adjustments = weight * (len(symbol_indices) / self.n_symbols)
            for idx in symbol_indices:
                adjusted_qtys[idx] *= cluster_adjustments

        return adjusted_qtys

    def _scale_to_target_vol(self, qtys: np.ndarray, cov_matrix: np.ndarray,
                            target_vol: float, max_scale: float = 2.0) -> np.ndarray:
        """
        Scale positions to meet target portfolio volatility.
        """
        current_vol = self._calculate_portfolio_volatility(qtys, cov_matrix)

        if current_vol > 0:
            scale_factor = target_vol / current_vol
            scale_factor = np.clip(scale_factor, 0.1, max_scale)  # Prevent extreme scaling
            qtys *= scale_factor

        return qtys

    def _calculate_portfolio_volatility(self, qtys: np.ndarray, cov_matrix: np.ndarray) -> float:
        """Calculate portfolio volatility from positions and covariance."""
        if np.all(qtys == 0):
            return 0.0

        try:
            port_var = qtys.T @ cov_matrix @ qtys
            return max(0.0, float(np.sqrt(port_var)))
        except (ValueError, np.linalg.LinAlgError):
            return 0.0

    def get_cluster_contributions(self, qtys: np.ndarray, cov_matrix: np.ndarray,
                                 clusters: Dict[int, List[int]]) -> Dict[int, float]:
        """
        Calculate marginal risk contribution of each cluster.

        Returns:
            Dict of cluster_id -> risk contribution (fraction of port vol)
        """
        port_vol = self._calculate_portfolio_volatility(qtys, cov_matrix)
        if port_vol == 0:
            return {cid: 1.0 / len(clusters) for cid in clusters.keys()}

        contributions = {}
        port_var = port_vol ** 2

        for cluster_id, symbol_indices in clusters.items():
            if len(symbol_indices) == 0:
                contributions[cluster_id] = 0.0
                continue

            q_cluster = qtys[symbol_indices]
            Σ_cluster = cov_matrix[np.ix_(symbol_indices, symbol_indices)]
            cluster_marginal_risk = float(q_cluster.T @ Σ_cluster @ q_cluster)

            contributions[cluster_id] = cluster_marginal_risk / port_var

        return contributions

    def assess_cluster_stability(self, cluster_labels: np.ndarray,
                                historical_labels: List[np.ndarray]) -> Dict[str, float]:
        """
        Assess how stable cluster assignments are over time.

        Args:
            cluster_labels: Current cluster assignments
            historical_labels: List of past cluster assignments

        Returns:
            Stability metrics
        """
        if not historical_labels or len(historical_labels) < 3:
            return {"stability_score": 1.0, "transition_rate": 0.0}

        # Compute average Jaccard similarity over history
        similarities = []

        for hist_labels in historical_labels[-min(10, len(historical_labels)):]:  # Last 10 periods
            # Compute adjusted Rand index or simple overlap
            current_set = set(f"{i}_{c}" for i, c in enumerate(cluster_labels))
            hist_set = set(f"{i}_{c}" for i, c in enumerate(hist_labels))

            if current_set or hist_set:
                intersection = len(current_set & hist_set)
                union = len(current_set | hist_set)
                jaccard = intersection / union if union > 0 else 1.0
                similarities.append(jaccard)

        avg_similarity = np.mean(similarities) if similarities else 1.0

        # For transition rate, count symbol switches
        transitions = sum(1 for i in range(len(cluster_labels))
                         for hist_lab in historical_labels[-5:]  # Recent history
                         if i < len(hist_lab) and cluster_labels[i] != hist_lab[i])

        avg_transitions = transitions / (len(cluster_labels) * max(1, len(historical_labels[-5:]))) if cluster_labels.size > 0 else 0.0

        return {
            "stability_score": float(avg_similarity),  # 1.0 = perfectly stable
            "transition_rate": float(avg_transitions),  # Fraction ofassignments that changed
        }

    def should_recluster(self, cluster_labels: np.ndarray,
                        historical_labels: List[np.ndarray]) -> bool:
        """
        Determine if correlation structure changed enough to warrant reclustering.
        """
        stability = self.assess_cluster_stability(cluster_labels, historical_labels)
        min_stability = 0.6  # Threshold for reclustering

        return stability["stability_score"] < min_stability

    def optimize_cluster_weights(self, cluster_sizes: Dict[int, int],
                               cluster_risks: Dict[int, float]) -> Dict[int, float]:
        """
        Optimize cluster weights based on sizes and current risks (simplified).

        Args:
            cluster_sizes: Dict of cluster_id -> number of symbols
            cluster_risks: Dict of cluster_id -> current risk contribution

        Returns:
            Optimal cluster risk weights
        """
        if not cluster_sizes or not cluster_risks:
            return {}

        # Simple size-weighted exponentiated risk (inverse boosting)
        weights = {}
        total_adjustment = 0

        for cid in cluster_sizes.keys():
            size_factor = np.log(cluster_sizes[cid] + 1)  # Reward larger clusters moderately
            risk_factor = 1.0 / (1.0 + cluster_risks[cid])  # Reduce weight of high-risk clusters
            weights[cid] = size_factor * risk_factor
            total_adjustment += weights[cid]

        # Normalize
        if total_adjustment > 0:
            weights = {cid: w / total_adjustment for cid, w in weights.items()}

        return weights
