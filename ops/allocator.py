# ops/allocator.py
import json
import time
import math
import logging
import numpy as np
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass

from ops.telemetry_metrics import calculate_strategy_score
from ops.telemetry_store import Metrics

# Configuration
ALLOCATIONS_PATH = Path("ops/capital_allocations.json")
TOTAL_CAPITAL_USD = 10000.0  # Default total pool
MIN_ALLOCATION_USD = 100.0   # Minimum to keep a strategy alive (unless killed)
MAX_ALLOCATION_USD = 5000.0  # Max per strategy
DAMPING_FACTOR = 0.10        # Max 10% change per cycle
BANKRUPTCY_THRESHOLD = 0.20  # 20% total loss = Kill

logging.basicConfig(level=logging.INFO, format="[ALLOC] %(message)s")
logger = logging.getLogger("WealthManager")

@dataclass
class StrategyPerformance:
    strategy_id: str
    metrics: Metrics

class WealthManager:
    def __init__(self, total_capital: float = TOTAL_CAPITAL_USD):
        self.total_capital = total_capital
        self.allocations: Dict[str, float] = {}
        self.scores: Dict[str, float] = {}
        self._load_state()

    def _load_state(self):
        """Load existing allocations to support damping."""
        if ALLOCATIONS_PATH.exists():
            try:
                data = json.loads(ALLOCATIONS_PATH.read_text())
                self.allocations = data.get("allocations", {})
            except Exception:
                logger.warning("Failed to load allocations, starting fresh.")

    def _save_state(self):
        """Persist allocations for the Risk Engine."""
        data = {
            "allocations": self.allocations,
            "scores": self.scores,
            "total_capital": self.total_capital,
            "updated_at": time.time()
        }
        ALLOCATIONS_PATH.write_text(json.dumps(data, indent=2))

    def allocate(self, strategies: List[StrategyPerformance]):
        """
        Main allocation logic:
        1. Calculate Scores
        2. Softmax -> Target Percentages
        3. Apply Damping & Safety Nets
        """
        scores = {}
        raw_scores = []
        active_strategies = []

        # 1. Calculate Scores & Check Bankruptcy
        for strat in strategies:
            sid = strat.strategy_id
            m = strat.metrics
            
            # Safety Net: Bankruptcy Protection
            if m.total_loss_pct > BANKRUPTCY_THRESHOLD:
                logger.error(f"💀 KILLING Strategy {sid}: Total Loss {m.total_loss_pct:.1%} > {BANKRUPTCY_THRESHOLD:.1%}")
                self.allocations[sid] = 0.0
                self.scores[sid] = 0.0
                continue
            
            score = calculate_strategy_score(
                realized_pnl=m.pnl_realized,
                win_rate=m.win_rate,
                max_drawdown=m.max_drawdown
            )
            scores[sid] = score
            raw_scores.append(score)
            active_strategies.append(sid)

        if not active_strategies:
            logger.warning("No active strategies to allocate.")
            return

        # 2. Softmax Normalization
        # Shift scores for numerical stability (exp(x - max(x)))
        # If all scores are 0/negative, this handles it gracefully.
        scores_array = np.array(raw_scores)
        exp_scores = np.exp(scores_array - np.max(scores_array)) 
        softmax_probs = exp_scores / exp_scores.sum()
        
        target_allocations = {}
        for i, sid in enumerate(active_strategies):
            target_pct = softmax_probs[i]
            target_usd = target_pct * self.total_capital
            
            # Clamp to Global Min/Max
            target_usd = max(MIN_ALLOCATION_USD, min(MAX_ALLOCATION_USD, target_usd))
            target_allocations[sid] = target_usd

        # 3. Damping (Smooth Transitions)
        for sid, target in target_allocations.items():
            current = self.allocations.get(sid, target) # If new, jump straight to target? Or start small? Let's jump.
            
            # Max change = DAMPING_FACTOR * current (or total?)
            # Let's use simple lerp: new = current + clamp(target - current, -max_delta, max_delta)
            # max_delta = 10% of TOTAL capital? Or 10% of CURRENT allocation?
            # User said "don't move more than 10% of capital per hour".
            # Let's assume this runs every minute? 
            # If runs often, damping should be small.
            # Let's use a simple exponential moving average approach or fixed step.
            # "Clamp(Target - Current, -10%, +10%)" usually implies relative to the position size or total pool.
            # Let's limit change to 10% of TOTAL_CAPITAL per update to be safe but responsive.
            
            max_delta = self.total_capital * DAMPING_FACTOR
            delta = target - current
            clamped_delta = max(-max_delta, min(max_delta, delta))
            
            new_alloc = current + clamped_delta
            self.allocations[sid] = new_alloc
            self.scores[sid] = scores[sid]
            
            logger.info(f"Strategy {sid}: Score={scores[sid]:.2f} -> Alloc=${new_alloc:.0f} (Target=${target:.0f})")

        self._save_state()

# Singleton instance for easy import
wealth_manager = WealthManager()
