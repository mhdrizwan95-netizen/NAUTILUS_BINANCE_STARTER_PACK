#!/usr/bin/env python3
# strategies/hmm_policy/reward_tables.py — M15: Exponential moving average reward tracking
from collections import defaultdict
from typing import Dict, Tuple, Optional, Any
import pickle
import os
from pathlib import Path
import numpy as np

class EMATable:
    """
    Exponential Moving Average table for reward tracking.
    Provides forgetful memory: recent rewards matter more than old ones.
    """

    def __init__(self, alpha: float = 0.02):
        """
        Initialize EMA table.

        Args:
            alpha: Decay factor (0 < alpha <= 1). Higher = faster adaptation.
        """
        self.alpha = min(max(alpha, 1e-6), 1.0)  # Clamp to valid range
        self.avg = defaultdict(float)  # key -> current EMA value
        self.n = defaultdict(int)  # key -> observation count

    def update(self, key: Any, reward: float):
        """
        Update EMA for a key with new reward observation.

        Args:
            key: State/action identifier (hashable)
            reward: Observed reward value
        """
        if not isinstance(reward, (int, float)) or not isinstance(reward, (int, float)):
            return  # Skip invalid rewards

        if np.isnan(reward) or np.isinf(reward):
            return  # Skip NaN/inf rewards

        # EMA update: new_avg = (1-alpha) * old_avg + alpha * new_value
        old_avg = self.avg.get(key, 0.0)
        self.avg[key] = (1.0 - self.alpha) * old_avg + self.alpha * reward
        self.n[key] += 1

    def get(self, key: Any, default: float = 0.0) -> float:
        """Get current EMA value for key."""
        return self.avg.get(key, default)

    def get_count(self, key: Any) -> int:
        """Get observation count for key."""
        return self.n.get(key, 0)

    def get_all_keys(self) -> list:
        """Get all keys that have been observed."""
        return list(self.avg.keys())

    def get_top_rewards(self, limit: int = 10) -> list[Tuple[Any, float]]:
        """Get top N rewards by EMA value."""
        items = list(self.avg.items())
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:limit]

    def get_bottom_rewards(self, limit: int = 10) -> list[Tuple[Any, float]]:
        """Get bottom N rewards by EMA value."""
        items = list(self.avg.items())
        items.sort(key=lambda x: x[1])
        return items[:limit]

    def flatten(self) -> Dict[str, Any]:
        """Flatten to dict for serialization."""
        return {
            'avg': dict(self.avg),
            'n': dict(self.n),
            'alpha': self.alpha
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'EMATable':
        """Reconstruct from dictionary."""
        table = cls(alpha=data.get('alpha', 0.02))
        table.avg.update(data.get('avg', {}))
        table.n.update(data.get('n', {}))
        return table

    def __len__(self) -> int:
        """Number of keys with data."""
        return len(self.avg)

    def __repr__(self) -> str:
        return f"EMATable(alpha={self.alpha}, keys={len(self)})"

class RewardBook:
    """
    Maintains EMA rewards for different trade decision contexts.
    Tracks what actually works in real trading, not just training data.
    """

    def __init__(self, alpha_state: float = 0.02, alpha_action: float = 0.02):
        """
        Initialize reward tracking.

        Args:
            alpha_state: Decay for state-level rewards (slower learning)
            alpha_action: Decay for action-specific rewards (faster learning)
        """
        self.state = EMATable(alpha_state)        # (macro_state, micro_state) -> marginal reward
        self.state_side = EMATable(alpha_action)  # (macro_state, micro_state, side) -> side-specific reward
        self.last_update_ts = 0.0
        self.session_rewards = []  # For diagnostics, cleared per session

    def update(self, macro_state: int, micro_state: int, side: str, delta_pnl: float):
        """
        Update reward tables with observed trade outcome.

        Args:
            macro_state: Current macro state
            micro_state: Current micro state
            side: Trade side (BUY/SELL/HOLD, though HOLD not usually traded)
            delta_pnl: Realized P&L for this trade
        """
        # Skip invalid inputs
        if not isinstance(macro_state, int) or not isinstance(micro_state, int):
            return
        if side not in ['BUY', 'SELL', 'HOLD']:
            return
        if not isinstance(delta_pnl, (int, float)) or np.isnan(delta_pnl) or np.isinf(delta_pnl):
            return

        state_key = (macro_state, micro_state)
        action_key = (macro_state, micro_state, side)

        # Update both tables
        self.state.update(state_key, delta_pnl)
        self.state_side.update(action_key, delta_pnl)

        # Track for diagnostics
        self.session_rewards.append({
            'state': state_key,
            'action': action_key,
            'reward': delta_pnl,
            'timestamp': self.last_update_ts
        })

    def expected_edge(self, macro_state: int, micro_state: int, side: str) -> float:
        """
        Calculate expected edge for a decision context.
        Blends state-level marginal reward with action-specific preference.

        Args:
            macro_state: Macro state
            micro_state: Micro state
            side: Trade side

        Returns:
            Expected edge (positive = profitable, negative = loss-making)
        """
        state_key = (macro_state, micro_state)
        action_key = (macro_state, micro_state, side)

        # State-level marginal (what generally works in this state)
        state_reward = self.state.get(state_key, 0.0)

        # Action-specific preference (if this side works better/worse)
        action_reward = self.state_side.get(action_key, 0.0)

        # Blend: trust action-specific if we have data, otherwise fall back to state
        state_count = self.state.get_count(state_key)
        action_count = self.state_side.get_count(action_key)

        if action_count >= 3:  # Enough action-specific data
            # 70% action-specific, 30% state marginal
            edge = 0.7 * action_reward + 0.3 * state_reward
        else:
            # Fall back to state marginal
            edge = state_reward

        return edge

    def get_state_ranking(self) -> list[Tuple[Tuple[int, int], float]]:
        """Rank states by profitability."""
        return self.state.get_top_rewards(limit=50)  # Top 50 states

    def get_action_ranking(self) -> list[Tuple[Tuple[int, int, str], float]]:
        """Rank state-actions by profitability."""
        return self.state_side.get_top_rewards(limit=50)

    def get_worst_states(self) -> list[Tuple[Tuple[int, int], float]]:
        """Identify consistently unprofitable states."""
        return self.state.get_bottom_rewards(limit=10)

    def get_performance_stats(self) -> Dict[str, float]:
        """Get overall performance statistics."""
        state_entries = len(self.state)
        action_entries = len(self.state_side)

        if state_entries == 0:
            return {
                'states_observed': 0,
                'actions_observed': 0,
                'avg_state_reward': 0.0,
                'avg_action_reward': 0.0
            }

        state_rewards = list(self.state.avg.values())
        action_rewards = list(self.state_side.avg.values())

        return {
            'states_observed': state_entries,
            'actions_observed': action_entries,
            'avg_state_reward': sum(state_rewards) / len(state_rewards),
            'avg_action_reward': sum(action_rewards) / len(action_rewards),
            'profitable_states': sum(1 for r in state_rewards if r > 0),
            'profitable_actions': sum(1 for r in action_rewards if r > 0)
        }

    def save_to_file(self, filepath: Path):
        """Persist reward tables to disk."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'state': self.state.flatten(),
            'state_side': self.state_side.flatten(),
            'alpha_state': self.state.alpha,
            'alpha_action': self.state_side.alpha,
            'last_update_ts': self.last_update_ts
        }
        with open(filepath, 'wb') as f:
            pickle.dump(data, f)

    def load_from_file(self, filepath: Path) -> bool:
        """Load reward tables from disk."""
        if not filepath.exists():
            return False

        try:
            with open(filepath, 'rb') as f:
                data = pickle.load(f)

            self.state = EMATable.from_dict(data['state'])
            self.state_side = EMATable.from_dict(data['state_side'])
            self.last_update_ts = data.get('last_update_ts', 0.0)

            # Override alphas if they changed
            if 'alpha_state' in data:
                self.state.alpha = data['alpha_state']
            if 'alpha_action' in data:
                self.state_side.alpha = data['alpha_action']

            return True
        except (pickle.PickleError, KeyError, ValueError):
            return False

    def reset_session(self):
        """Reset per-session diagnostics."""
        self.session_rewards.clear()

    def get_diagnostics(self) -> Dict[str, Any]:
        """Get diagnostic information for monitoring."""
        return {
            'performance_stats': self.get_performance_stats(),
            'top_states': self.get_state_ranking()[:5],  # Top 5
            'worst_states': self.get_worst_states(),
            'session_rewards_count': len(self.session_rewards),
            'avg_session_reward': (sum(r['reward'] for r in self.session_rewards) /
                                 len(self.session_rewards)) if self.session_rewards else 0.0
        }

    def __repr__(self) -> str:
        stats = self.get_performance_stats()
        return f"RewardBook(states={stats['states_observed']}, actions={stats['actions_observed']}, avg_reward={stats['avg_state_reward']:.4f})"

# Global reward book instance
_global_reward_book: Optional[RewardBook] = None

def get_global_reward_book(data_dir: Path, alpha_state: float = 0.02, alpha_action: float = 0.02) -> RewardBook:
    """Get or create global reward book instance."""
    global _global_reward_book
    if _global_reward_book is None:
        _global_reward_book = RewardBook(alpha_state, alpha_action)

        # Try to load from disk
        reward_file = data_dir / "reward_book.pkl"
        _global_reward_book.load_from_file(reward_file)

    return _global_reward_book
