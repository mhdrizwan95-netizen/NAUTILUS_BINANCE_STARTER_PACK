#!/usr/bin/env python3
# strategies/hmm_policy/analysis/transition_monitor.py — M13.1: Live transition matrix drift detection
import numpy as np
from collections import defaultdict
from typing import Optional, Dict, List
from datetime import timedelta

class TransitionMonitor:
    """Tracks empirical HMM state transition matrices and computes KL divergence from baseline."""

    def __init__(self, n_states: int, window_size: int = 10000):
        self.n_states = n_states
        self.window_size = window_size

        # Rolling transition counts (from_state -> to_state -> count)
        self.transition_counts: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        self.state_counts: Dict[int, float] = defaultdict(float)

        # Baseline transition matrix (from training or initial data)
        self.baseline_matrix: Optional[np.ndarray] = None
        self.baseline_counts: Optional[Dict[int, Dict[int, float]]] = None

        # Historical state sequence for rolling window
        self.state_history: List[int] = []
        self.timestamp_history: List[int] = []  # ns timestamps

        # Metrics
        self.current_drift_score = 0.0
        self.transition_entropy = 0.0
        self.total_transitions = 0

    def update_baseline(self, training_states: List[int]):
        """Set baseline transition matrix from training data."""
        if len(training_states) < 10:
            return

        # Count transitions in training data
        baseline_counts = defaultdict(lambda: defaultdict(float))
        baseline_state_counts = defaultdict(float)

        for i in range(1, len(training_states)):
            from_state = training_states[i-1]
            to_state = training_states[i]
            baseline_counts[from_state][to_state] += 1
            baseline_state_counts[from_state] += 1

        # Convert to probability matrix
        self.baseline_counts = baseline_counts
        baseline_matrix = np.zeros((self.n_states, self.n_states))

        for from_state in range(self.n_states):
            total_from = sum(baseline_counts[from_state].values())
            if total_from > 0:
                for to_state in range(self.n_states):
                    baseline_matrix[from_state, to_state] = baseline_counts[from_state][to_state] / total_from

        self.baseline_matrix = baseline_matrix

    def record_transition(self, from_state: int, to_state: int, timestamp_ns: int):
        """Record a single state transition."""
        if from_state is None or to_state is None:
            return

        # Update rolling counts
        self.state_history.append(from_state)
        self.timestamp_history.append(timestamp_ns)
        self.transition_counts[from_state][to_state] += 1
        self.state_counts[from_state] += 1
        self.total_transitions += 1

        # Maintain window size
        if len(self.state_history) > self.window_size:
            old_from_state = self.state_history.pop(0)
            self.timestamp_history.pop(0)
            # Very approximate: reduce counts by small fraction (not perfectly rolling)
            # In production would track timestamps more rigorously
            for to_state in range(self.n_states):
                if self.transition_counts[old_from_state][to_state] > 0:
                    self.transition_counts[old_from_state][to_state] -= 1 / self.window_size
                if self.transition_counts[old_from_state][to_state] < 0:
                    self.transition_counts[old_from_state][to_state] = 0
            if self.state_counts[old_from_state] > 0:
                self.state_counts[old_from_state] -= 1 / self.window_size
            self.total_transitions -= 1 / self.window_size

        # Update metrics
        self._update_metrics()

    def _update_metrics(self):
        """Compute current transition matrix and KL divergence."""
        if self.baseline_matrix is None or self.total_transitions < 10:
            self.current_drift_score = 0.0
            self.transition_entropy = 0.0
            return

        # Build current transition matrix
        current_matrix = np.zeros((self.n_states, self.n_states))
        total_entropy = 0.0

        for from_state in range(self.n_states):
            total_from = sum(self.transition_counts[from_state].values())
            if total_from > 0:
                row_entropy = 0.0
                for to_state in range(self.n_states):
                    prob = self.transition_counts[from_state][to_state] / total_from
                    current_matrix[from_state, to_state] = prob
                    if prob > 0:
                        row_entropy -= prob * np.log(prob)
                total_entropy += row_entropy * (total_from / self.total_transitions)

        # KL divergence with Dirichlet smoothing (avoid 0 probs)
        if np.all(current_matrix > 0) and np.all(self.baseline_matrix > 0):
            epsilon = 1e-6  # Avoid log(0)
            smoothed_current = current_matrix + epsilon
            smoothed_baseline = self.baseline_matrix + epsilon

            smoothed_current /= smoothed_current.sum(axis=1, keepdims=True)
            smoothed_baseline /= smoothed_baseline.sum(axis=1, keepdims=True)

            kl_div = np.sum(smoothed_baseline * np.log(smoothed_baseline / smoothed_current))
            self.current_drift_score = max(0, float(kl_div))
        else:
            self.current_drift_score = 0.0

        self.transition_entropy = max(0, float(total_entropy))

    def get_metrics(self) -> Dict[str, float]:
        """Return current monitoring metrics for Prometheus export."""
        return {
            "transition_drift_score": self.current_drift_score,
            "transition_entropy": self.transition_entropy,
            "total_transitions": self.total_transitions,
        }

    def is_drift_alert(self, threshold: float = 0.2) -> bool:
        """Check if current drift exceeds threshold."""
        return self.current_drift_score > threshold

    def get_transition_matrix(self) -> np.ndarray:
        """Return current transition matrix."""
        matrix = np.zeros((self.n_states, self.n_states))
        for from_state in range(self.n_states):
            total = sum(self.transition_counts[from_state].values())
            if total > 0:
                for to_state in range(self.n_states):
                    matrix[from_state, to_state] = self.transition_counts[from_state][to_state] / total
        return matrix

    def get_transition_heatmap_data(self) -> List[List[float]]:
        """Return data for heatmap visualization."""
        matrix = self.get_transition_matrix()
        return matrix.tolist()

    def reset_window(self):
        """Reset rolling window (useful for retraining)."""
        self.state_history.clear()
        self.timestamp_history.clear()
        self.transition_counts.clear()
        self.state_counts.clear()
        self.total_transitions = 0
        self._update_metrics()
