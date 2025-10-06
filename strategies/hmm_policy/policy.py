# M12: dynamic sizing policy + M15: online learning integration
import numpy as np
from typing import Tuple, Literal, Optional
from pathlib import Path

Action = Tuple[Literal["BUY","SELL","HOLD"], float, float | None]

# Static edge priors (fallback when no learning data)
STATE_EDGE = {0: 0.0, 1: 1.0, 2: -1.0}  # example: state 1 -> bullish, state 2 -> bearish

# Global reward book for learned edges (initialized lazily)
_reward_book = None
_online_trainer = None

def _get_reward_book(data_dir: Optional[Path] = None) -> Optional[any]:
    """Lazily load reward book for learned edges."""
    global _reward_book
    if _reward_book is None:
        try:
            from .reward_tables import get_global_reward_book
            if data_dir is None:
                # Default to processed data dir
                data_dir = Path("data/processed")
            _reward_book = get_global_reward_book(data_dir)
        except ImportError:
            _reward_book = None
    return _reward_book

def _get_online_trainer(feature_dim: int = 11, data_dir: Optional[Path] = None) -> Optional[any]:
    """Lazily load online trainer for model adaptation."""
    global _online_trainer
    if _online_trainer is None:
        try:
            from .online_trainer import get_global_online_trainer
            if data_dir is None:
                data_dir = Path("data/processed")
            _online_trainer = get_global_online_trainer(feature_dim, data_dir)
        except ImportError:
            _online_trainer = None
    return _online_trainer

def decide_action(state, conf, feats, cfg, *, symbol_cfg, vol_bp, mid_px, data_dir=None, online_finetune=False) -> Action:
    """
    Enhanced decision making that blends:
    1. HMM confidence + static state priors
    2. Learned EMA reward estimates
    3. Online neural policy adaptation (optional)
    """
    # Get learned components (if available)
    reward_book = _get_reward_book(data_dir)
    online_trainer = _get_online_trainer(len(feats), data_dir) if online_finetune else None

    # Base edge from HMM confidence + static priors
    static_prior = STATE_EDGE.get(state, 0.0)
    hmm_edge = static_prior * (2 * conf - 1)  # Confidence-scaled prior

    # Add learned rewards if available
    learned_edge = 0.0
    if reward_book and online_trainer:
        # Macro/micro state for reward book (need to extend to use actual M/S from caller)
        # For now, map single HMM state to both
        macro_state = state // 2  # Simple mapping
        micro_state = state

        # State-level reward (what generally works in this regime)
        state_reward = reward_book.expected_edge(macro_state, micro_state, "BUY") - \
                      reward_book.expected_edge(macro_state, micro_state, "SELL")

        # Online model probability (shifts mass toward or away from 0.5)
        online_prob = online_trainer.score(feats)

        # Blend: 40% HMM, 30% learned rewards, 30% online model
        learned_edge = (state_reward + (online_prob - 0.5) * 2.0) * 0.3

    # Combine all sources
    total_edge = hmm_edge * 0.7 + learned_edge

    # Clip to reasonable range
    total_edge = float(np.clip(total_edge, -1.0, 1.0))

    # Quantity scaling: inverse volatility sizing
    vol_term = max(vol_bp, 5.0)  # Avoid divide-by-zero
    qty = cfg.qty_k * abs(total_edge) / vol_term
    qty = float(np.clip(qty, cfg.qty_min, cfg.qty_max))

    # Direction decision
    if total_edge > 0.01:
        side = "BUY"
    elif total_edge < -0.01:
        side = "SELL"
    else:
        side = "HOLD"
        qty = 0

    # Ensure minimum notional
    if mid_px * qty < symbol_cfg.min_notional_usd:
        qty = max(symbol_cfg.min_notional_usd / max(mid_px, 1e-9), cfg.qty_min)
        if qty > cfg.qty_max:
            side = "HOLD"  # Can't meet requirements
            qty = 0

    return (side, qty, None)
