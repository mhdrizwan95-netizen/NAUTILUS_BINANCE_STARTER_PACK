"""
FeeManager - Automatic BNB topup for fee discounts.

Monitors BNB balance and automatically buys more BNB when balance falls below threshold.
This ensures trading fees are always paid in BNB to maximize fee discounts:
- Spot trading: 25% fee discount when using BNB
- Futures trading: 10% fee discount when using BNB
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)


@dataclass
class FeeManagerConfig:
    enabled: bool = True
    bnb_topup_threshold_usd: float = 10.0  # Trigger topup when BNB < $10
    bnb_topup_amount_usd: float = 50.0  # Buy $50 worth of BNB
    check_interval_sec: float = 1800.0  # Check every 30 minutes
    min_topup_interval_sec: float = 3600.0  # Don't topup more than once per hour


class FeeManager:
    """Daemon that auto-tops-up BNB balance for fee discounts."""

    def __init__(
        self,
        portfolio,
        order_router,
        *,
        config: FeeManagerConfig | None = None,
    ):
        self.portfolio = portfolio
        self.router = order_router
        self.config = config or FeeManagerConfig()
        self._last_topup_ts = 0.0
        self._running = False

    async def run(self) -> None:
        """Main loop: check BNB balance periodically and topup if needed."""
        if not self.config.enabled:
            _LOGGER.info("[FeeManager] Disabled via config")
            return

        self._running = True
        _LOGGER.info("[FeeManager] Started (threshold=$%.2f, amount=$%.2f, interval=%ds)",
                     self.config.bnb_topup_threshold_usd,
                     self.config.bnb_topup_amount_usd,
                     self.config.check_interval_sec)

        while self._running:
            try:
                await asyncio.sleep(self.config.check_interval_sec)
                await self._check_and_topup()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _LOGGER.warning("[FeeManager] Check failed: %s", exc, exc_info=True)

    async def _check_and_topup(self) -> None:
        """Check BNB balance and execute topup if below threshold."""
        # Get current BNB balance\n        bnb_balance = self.portfolio.get_balance("BNB")
        
        # Get BNB/USDT price to calculate USD value
        try:
            bnb_price = await self.router._get_cached_price("BNBUSDT", market="spot")
        except Exception as exc:
            _LOGGER.warning("[FeeManager] Failed to get BNB price: %s", exc)
            return

        bnb_value_usd = bnb_balance * bnb_price

        # Check if topup needed
        if bnb_value_usd >= self.config.bnb_topup_threshold_usd:
            _LOGGER.debug("[FeeManager] BNB balance OK: %.4f BNB ($%.2f)", bnb_balance, bnb_value_usd)
            return

        # Check topup cooldown
        now = time.time()
        if now - self._last_topup_ts < self.config.min_topup_interval_sec:
            _LOGGER.debug("[FeeManager] Topup cooldown active (%.0fs remaining)",
                          self.config.min_topup_interval_sec - (now - self._last_topup_ts))
            return

        # Calculate quantity to buy\n        bnb_qty = self.config.bnb_topup_amount_usd / bnb_price

        _LOGGER.info("[FeeManager] BNB low (%.4f BNB, $%.2f). Topping up %.4f BNB ($%.2f)...",
                     bnb_balance, bnb_value_usd, bnb_qty, self.config.bnb_topup_amount_usd)

        try:
            # Execute LIMIT IOC buy order for BNB
            result = await self.router.place_order(
                symbol="BNBUSDT",
                side="BUY",
                quantity=bnb_qty,
                market="spot",
                order_type="LIMIT_IOC",  # Immediate-or-cancel limit order
            )
            
            self._last_topup_ts = now
            _LOGGER.info("[FeeManager] ✅ Topped up BNB to save fees: %s", result.get("orderId"))
        
        except Exception as exc:
            _LOGGER.error("[FeeManager] Topup failed: %s", exc, exc_info=True)

    def stop(self) -> None:
        """Stop the daemon."""
        self._running = False
        _LOGGER.info("[FeeManager] Stopped")


def load_fee_manager_config() -> FeeManagerConfig:
    """Load FeeManager config from environment variables."""
    return FeeManagerConfig(
        enabled=os.getenv("BNB_FEE_DISCOUNT_ENABLED", "true").lower() in {"1", "true", "yes"},
        bnb_topup_threshold_usd=float(os.getenv("BNB_TOPUP_THRESHOLD_USD", "10.0")),
        bnb_topup_amount_usd=float(os.getenv("BNB_TOPUP_AMOUNT_USD", "50.0")),
        check_interval_sec=float(os.getenv("BNB_TOPUP_INTERVAL_SEC", "1800.0")),
        min_topup_interval_sec=float(os.getenv("BNB_MIN_TOPUP_INTERVAL_SEC", "3600.0")),
    )
