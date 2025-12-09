"""
Liquidation Strategy (The Predator).

Execution Logic:
1.  Receive `signal.liquidation_cluster` (Velocity > Threshold).
2.  Direction:
    *   If Liquidation Side = SELL (Longs getting wrecked), Price is crashing.
    *   We want to CATCH the knife (Mean Reversion).
    *   Signal Side = BUY.
3.  Execution:
    *   Do NOT smash market order (slippage risk).
    *   Place a "Ladder" of Limit IOC orders below current price.
    *   Example: Current=100. Place Bids at 99.5, 99.0, 98.5.
4.  Risk Management:
    *   Immediate Stop Loss (-1%).
    *   Quick Take Profit (+0.5% - +1.0%).
    *   Time-based exit (30s) if stuck.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field

from engine.config import env_bool, env_float, env_int

_LOGGER = logging.getLogger("engine.strategies.liquidation")


@dataclass
class GridStep:
    """Single step in the ladder grid."""
    offset_pct: float  # Price offset from trigger (e.g., 0.005 = 0.5%)
    weight: float      # Size weight (e.g., 0.30 = 30% of total size)


@dataclass(frozen=True)
class LiquidationConfig:
    enabled: bool
    dry_run: bool
    size_usd: float
    stop_loss_pct: float
    take_profit_pct: float
    time_limit_sec: float
    max_inventory_usd: float
    # Grid configuration
    grid_steps: tuple[GridStep, ...] = field(default_factory=tuple)


def _parse_grid_config() -> tuple[GridStep, ...]:
    """
    Parse grid configuration from environment.
    
    Format: LIQU_GRID_CONFIG='[{"offset": 0.005, "weight": 0.30}, ...]'
    Default: 3-step ladder at 0.5%, 1.0%, 1.5% with 30/30/40 weighting
    """
    default_grid = [
        {"offset": 0.005, "weight": 0.30},  # Step 1: -0.5%, 30% size
        {"offset": 0.010, "weight": 0.30},  # Step 2: -1.0%, 30% size
        {"offset": 0.015, "weight": 0.40},  # Step 3: -1.5%, 40% size
    ]
    
    raw = os.getenv("LIQU_GRID_CONFIG", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                steps = []
                for item in parsed:
                    offset = float(item.get("offset", 0.005))
                    weight = float(item.get("weight", 0.33))
                    steps.append(GridStep(offset_pct=offset, weight=weight))
                if steps:
                    # Normalize weights to sum to 1.0
                    total_weight = sum(s.weight for s in steps)
                    if total_weight > 0:
                        steps = [GridStep(s.offset_pct, s.weight / total_weight) for s in steps]
                    return tuple(steps)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            _LOGGER.warning("Failed to parse LIQU_GRID_CONFIG: %s. Using defaults.", e)
    
    # Use default grid
    return tuple(GridStep(offset_pct=item["offset"], weight=item["weight"]) for item in default_grid)


def load_liquidation_config() -> LiquidationConfig:
    return LiquidationConfig(
        enabled=env_bool("LIQU_ENABLED", True),
        dry_run=env_bool("LIQU_DRY_RUN", True),
        size_usd=env_float("LIQU_SIZE_USD", 100.0),
        stop_loss_pct=env_float("LIQU_STOP_LOSS_PCT", 0.01),
        take_profit_pct=env_float("LIQU_TAKE_PROFIT_PCT", 0.005),
        time_limit_sec=env_float("LIQU_TIME_LIMIT_SEC", 30.0),
        max_inventory_usd=env_float("LIQU_MAX_INVENTORY_USD", 1000.0),
        grid_steps=_parse_grid_config(),
    )


class LiquidationStrategyModule:
    def __init__(self, cfg: LiquidationConfig = None) -> None:
        self.cfg = cfg or load_liquidation_config()
        self.enabled = self.cfg.enabled
        self._active_inventory = {}
        
        _LOGGER.info(
            "Liquidation Strategy Loaded: enabled=%s, dry_run=%s, size=$%.0f, grid=%s",
            self.enabled,
            self.cfg.dry_run,
            self.cfg.size_usd,
            [(f"{s.offset_pct*100:.1f}%", f"{s.weight*100:.0f}%") for s in self.cfg.grid_steps]
        )

    def handle_signal(self, event: dict) -> list[dict] | None:
        """
        Input: signal.liquidation_cluster
        Output: List of Order Decisions (Ladder)
        """
        if not self.enabled:
            return None

        # Extract info
        symbol = event.get("symbol")
        velocity = event.get("velocity_usd", 0.0)
        trigger_side = event.get("trigger_side", "").upper()  # e.g. SELL (Longs liquidating)
        trigger_price = float(event.get("trigger_price", 0.0))
        
        if not symbol or not trigger_price:
            return None

        # LOGIC:
        # If trigger_side == SELL, it means Longs are liquidating (Price Down).
        # We want to BUY (Catch Knife).
        # If trigger_side == BUY, Shorts liquidating (Price Up).
        # We want to SELL (Fade Spike).
        
        my_side = "BUY" if trigger_side == "SELL" else "SELL"
        direction_mult = -1 if my_side == "BUY" else 1  # Buy below, Sell above
        
        _LOGGER.info(
            "⚔️ PREDATOR TRIGGER: %s Vel=$%.0f Trigger=%s -> Action=%s",
            symbol, velocity, trigger_side, my_side
        )

        decisions = []
        
        # Calculate Ladder using weighted grid
        for i, step in enumerate(self.cfg.grid_steps, start=1):
            # Calculate limit price with explicit offset
            # Buy: price * (1 - offset), Sell: price * (1 + offset)
            limit_px = trigger_price * (1.0 + direction_mult * step.offset_pct)
            
            # Calculate quantity using weighted size
            step_usd = self.cfg.size_usd * step.weight
            qty = step_usd / limit_px
            
            decision = {
                "symbol": symbol,
                "side": my_side,
                "price": limit_px,
                "quantity": qty,
                "type": "LIMIT",
                "time_in_force": "GTC",  # Stay in book (Maker) to catch the knife
                "tag": f"liqu_sniper_step_{i}",
                "meta": {
                    "strategy": "liquidation_sniper",
                    "step": i,
                    "offset_pct": step.offset_pct,
                    "weight": step.weight,
                    "stop_loss": self.cfg.stop_loss_pct,
                    "take_profit": self.cfg.take_profit_pct,
                    "ttl": self.cfg.time_limit_sec,
                    "order_type": "LIMIT",
                    "price": limit_px,
                    "time_in_force": "GTC"
                }
            }
            decisions.append(decision)
            
            _LOGGER.debug(
                "  Step %d: %s %.6f @ %.2f (offset=%.2f%%, weight=%.0f%%)",
                i, my_side, qty, limit_px, step.offset_pct * 100, step.weight * 100
            )
            
        return decisions

