#!/usr/bin/env python3
# strategies/hmm_policy/corr_cluster.py — M14.1: Adaptive correlation-based clustering
import numpy as np
from typing import List, Optional, Tuple, Dict
from sklearn.cluster import KMeans
from collections import defaultdict

class CorrClusterer:
    """
    Dynamic clustering of symbols based on correlation structure.
    Adapts number of clusters using inertia elbow method.
    """

    def __init__(self, n_clusters_range: Tuple[int, int] = (1, 4), random_state: int = 42,
                 min_samples_per_cluster: int = 2, stability_window: int = 10):
        """
        Initialize clusterer.

        Args:
            n_clusters_range: (min_k, max_k) to search
            random_state: For reproducibility
            min_samples_per_cluster: Minimum symbols per cluster
            stability_window: Window size for stability calculation
        """
        self.n_range = n_clusters_range
        self.random_state = random_state
        self.min_samples_per_cluster = min_samples_per_cluster
        self.stability_window = stability_window

        self.model: Optional[KMeans] = None
        self.labels: Optional[np.ndarray] = None
        self.n_clusters = 1

        # Stability tracking
        self.label_history: List[np.ndarray] = []
        self.stability_matrix = np.array([])

    def fit(self, corr_matrix: np.ndarray) -> np.ndarray:
        """
        Cluster symbols based on correlation matrix.

        Args:
            corr_matrix: Square correlation matrix

        Returns:
            Cluster labels for each symbol
        """
        if corr_matrix.size == 0 or corr_matrix.shape[0] <= 1:
            self.labels = np.zeros(corr_matrix.shape[0] if corr_matrix.size > 0 else 1, dtype=int)
            self.n_clusters = 1
            return self.labels

        # Select optimal k and fit
        k, model = self._select_optimal_k(corr_matrix)
        self.n_clusters = k
        self.model = model
        self.labels = model.labels_

        # Track stability
        self._update_stability()

        return self.labels

    def _select_optimal_k(self, corr_matrix: np.ndarray) -> Tuple[int, KMeans]:
        """
        Select optimal number of clusters using simplified elbow method.

        For small n_symbols, use correlation distance as clustering feature.
        """
        n_symbols = corr_matrix.shape[0]
        if n_symbols <= 1:
            return 1, self._create_dummy_model(n_symbols)

        # For correlation-based clustering: use correlation vectors as features
        # Each symbol's correlation profile with all others
        feature_matrix = corr_matrix.copy()

        # Normalize features
        row_norms = np.sqrt(np.sum(feature_matrix**2, axis=1, keepdims=True))
        row_norms[row_norms == 0] = 1.0  # Avoid division by zero
        feature_matrix = feature_matrix / row_norms

        # Knee finding via inertia drop analysis
        k_candidates, inertias, models = self._evaluate_k_range(feature_matrix)

        if len(k_candidates) == 0:
            return 1, self._create_dummy_model(n_symbols)

        # Find knee: point with maximum distance to line from first to last
        best_k = self._find_knee(k_candidates, inertias)

        # Get best model
        model_idx = k_candidates.index(best_k)
        best_model = models[model_idx]

        return best_k, best_model

    def _evaluate_k_range(self, feature_matrix: np.ndarray) -> Tuple[List[int], List[float], List[KMeans]]:
        """
        Evaluate models across k range and collect metrics.
        """
        k_candidates = []
        inertias = []
        models = []

        for k in range(self.n_range[0], min(self.n_range[1] + 1, feature_matrix.shape[0] + 1)):
            try:
                model = KMeans(
                    n_clusters=k,
                    n_init=10,
                    random_state=self.random_state,
                    max_iter=300,
                    tol=1e-4
                )
                model.fit(feature_matrix)
                k_candidates.append(k)
                inertias.append(model.inertia_)
                models.append(model)

                # Enforce minimum samples per cluster constraint
                labels, counts = np.unique(model.labels_, return_counts=True)
                if np.any(counts < self.min_samples_per_cluster):
                    # Remove this candidate
                    k_candidates.pop()
                    inertias.pop()
                    models.pop()

            except (ValueError, np.linalg.LinAlgError):
                continue

        return k_candidates, inertias, models

    def _find_knee(self, k_candidates: List[int], inertias: List[float]) -> int:
        """
        Find the "elbow" point in the inertia plot using distance to line method.
        """
        if len(k_candidates) <= 2:
            return k_candidates[0]

        # Line from first to last point
        k_arr = np.array(k_candidates)
        inert_arr = np.array(inertias)

        # Normalize to [0,1] for numerical stability
        k_norm = (k_arr - k_arr[0]) / (k_arr[-1] - k_arr[0]) if k_arr[-1] != k_arr[0] else k_arr - k_arr[0]
        inert_norm = (inert_arr - inert_arr[-1]) / (inert_arr[0] - inert_arr[-1]) if inert_arr[0] != inert_arr[-1] else inert_arr - inert_arr[-1]

        # Find max perpendicular distance (y - line_x)
        line_vals = k_norm  # Line from (0,0) to (1,1)
        distances = inert_norm - line_vals

        # Find point with maximum positive distance (sharpest elbow)
        max_dist_idx = np.argmax(distances[distances > 0]) if np.any(distances > 0) else 0

        return k_candidates[max_dist_idx]

    def _create_dummy_model(self, n_symbols: int) -> KMeans:
        """
        Create dummy model for edge cases.
        """
        model = KMeans(n_clusters=1, n_init=1, random_state=self.random_state)
        model.labels_ = np.zeros(n_symbols, dtype=int)
        model.inertia_ = 0.0
        return model

    def _update_stability(self):
        """
        Update cluster assignment stability over time window.
        """
        if self.labels is not None:
            self.label_history.append(self.labels.copy())

            # Keep window size
            if len(self.label_history) > self.stability_window:
                self.label_history.pop(0)

            # Compute stability matrix if enough history
            if len(self.label_history) >= 3:
                n_symbols = len(self.labels)
                stability_scores = np.zeros(n_symbols)

                for symbol_idx in range(n_symbols):
                    # Track how often this symbol stays in same cluster
                    symbol_labels = [labels[symbol_idx] for labels in self.label_history]
                    if len(symbol_labels) >= 3:
                        # Count transitions (normalized)
                        transitions = sum(1 for i in range(1, len(symbol_labels))
                                        if symbol_labels[i] != symbol_labels[i-1])
                        stability = 1.0 - (transitions / (len(symbol_labels) - 1))
                        stability_scores[symbol_idx] = max(0.0, stability)
                    else:
                        stability_scores[symbol_idx] = 1.0  # All same by default

                self.stability_matrix = stability_scores
            else:
                self.stability_matrix = np.ones(len(self.labels)) if self.labels is not None else np.array([])

    def get_cluster_membership(self) -> Dict[int, List[int]]:
        """
        Get mapping of cluster_id -> list of symbol indices.

        Returns:
            Dict mapping cluster ID to list of symbol indices
        """
        if self.labels is None:
            return {}

        clusters = defaultdict(list)
        for i, label in enumerate(self.labels):
            clusters[int(label)].append(i)

        return dict(clusters)

    def get_cluster_stats(self) -> Dict[str, float]:
        """
        Get clustering quality statistics.

        Returns:
            Dict with useful cluster metrics
        """
        if self.labels is None or self.model is None:
            return {
                "n_clusters": 1,
                "silhouette_score": 0.0,
                "avg_cluster_size": 0.0,
                "stability_score": 1.0
            }

        labels_count = np.bincount(self.labels)
        avg_size = float(np.mean(labels_count))
        stability = float(np.mean(self.stability_matrix)) if self.stability_matrix.size > 0 else 1.0

        # Simplified silhouette (would need full feature matrix in production)
        # For now, use cluster compactness as proxy
        compactness = self.model.inertia_ / len(self.labels) if len(self.labels) > 0 else 0.0

        return {
            "n_clusters": self.n_clusters,
            "compactness_score": compactness,
            "avg_cluster_size": avg_size,
            "stability_score": stability
        }

    def predict_cluster(self, symbol_idx: int) -> int:
        """
        Predict cluster assignment for a symbol index.

        Args:
            symbol_idx: Index of symbol to predict

        Returns:
            Predicted cluster label
        """
        if self.labels is None or symbol_idx >= len(self.labels):
            return 0

        return int(self.labels[symbol_idx])

    def get_cluster_labels(self) -> List[str]:
        """
        Get human-readable cluster labels.

        Returns:
            List of cluster label strings (e.g., "Cluster 0", "Cluster 1")
        """
        if self.labels is None:
            return ["Cluster 0"]

        unique_labels = sorted(np.unique(self.labels))
        return [f"Cluster {i}" for i in unique_labels]

    def reset_history(self):
        """
        Reset stability tracking history.
        Useful when correlation structure changes significantly.
        """
        self.label_history.clear()
        self.stability_matrix = np.array([])
