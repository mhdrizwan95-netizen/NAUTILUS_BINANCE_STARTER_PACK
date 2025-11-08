"""
OCO (One Cancels Other) and Trailing Stop order intelligence.

Provides automatic management of linked orders and dynamic stop adjustments.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from .oms_store import OMSStore
from .order_router import place_order
from .venues import get_venue

_oms = OMSStore()


async def oco_watcher(interval: int = 3) -> None:
    """
    Watcher daemon that monitors OCO groups and cancels sibling orders when one fills.

    Args:
        interval: Check interval in seconds
    """
    logging.info("[OCO] Watcher started with interval %ds", interval)
    while True:
        try:
            # Get open orders and group by OCO
            open_orders = list(_oms.list_open())
            grouped = {}
            for order in open_orders:
                if order.oco_group_id:
                    grouped.setdefault(order.oco_group_id, []).append(order)

            for group_id, orders in grouped.items():
                if len(orders) != 2:
                    continue  # Only handle pairs for now

                order_a, order_b = orders

                # Check if either is filled (basic check - could be enhanced)
                for order in [order_a, order_b]:
                    venue = order.symbol.split(".")[1]
                    ven_client = get_venue(venue).client

                    # Check order status (this could be enhanced with proper venue status calls)
                    current_status = order.status

                    if current_status == "FILLED":
                        # Cancel the sibling
                        sibling = order_b if order == order_a else order_a

                        if hasattr(ven_client, "cancel"):
                            try:
                                ven_client.cancel(
                                    order_id=sibling.venue_order_id,
                                    symbol=sibling.symbol,
                                )
                                _oms.close(sibling.id, "CANCELED")
                                logging.info(
                                    "[OCO] Group %s: %s filled, canceled sibling %s",
                                    group_id,
                                    order.symbol,
                                    sibling.symbol,
                                )
                            except Exception as e:
                                logging.error(
                                    "[OCO] Failed to cancel sibling %s: %s",
                                    sibling.id,
                                    e,
                                )
                        else:
                            logging.warning(
                                "[OCO] Venue client missing cancel method for %s",
                                sibling.symbol,
                            )

                        # Mark the filled order as closed too if not already
                        _oms.close(order.id, "FILLED")
                        break

        except Exception as e:
            logging.warning(f"[OCO] Watcher loop error: {e}")

        await asyncio.sleep(interval)


def create_oco_pair(order1_data: Dict[str, Any], order2_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create an OCO (One Cancels Other) pair of orders.

    Args:
        order1_data: First order parameters
        order2_data: Second order parameters

    Returns:
        Dict with OCO group info
    """
    group_id = uuid4().hex

    # Submit both orders with OCO group ID
    orders = []
    for idx, order_data in enumerate([order1_data, order2_data], 1):
        try:
            result = place_order(**order_data)

            # Update OMS record with OCO group
            order_rec = _oms.get(result.get("order_id_local", ""))
            if order_rec:
                order_rec.oco_group_id = group_id
                _oms.upsert(order_rec, f"OCO_LINK_{idx}")

            orders.append({"order_id": result.get("order_id_local"), "result": result})

        except Exception as e:
            logging.error(f"[OCO] Failed to place order {idx}: {e}")
            return {"error": f"Failed to place order {idx}: {str(e)}"}

    return {
        "oco_group_id": group_id,
        "orders": orders,
        "message": f"OCO group {group_id} created with {len(orders)} orders",
    }


class TrailingDaemon:
    """
    Daemon for managing trailing stops that adjust with price movements.
    """

    def __init__(self, interval: int = 5):
        self.interval = interval
        self.active_trails: Dict[str, Dict[str, Any]] = {}
        self._oms = OMSStore()

    def add_trailing_stop(
        self,
        symbol: str,
        side: str,
        trail_pct: Optional[float] = None,
        trail_usd: Optional[float] = None,
        quantity: float = 0.0,
        order_id: Optional[str] = None,
    ) -> str:
        """
        Add a trailing stop order.

        Args:
            symbol: Symbol to trail
            side: "BUY" or "SELL"
            trail_pct: Trail percentage (e.g., 5.0 for 5%)
            trail_usd: Fixed USD trail amount
            quantity: Quantity to trail
            order_id: Optional existing order to attach trail to

        Returns:
            Trail identifier
        """
        if not trail_pct and not trail_usd:
            raise ValueError("Must specify trail_pct or trail_usd")

        trail_id = f"trail_{symbol}_{side}_{int(time.time())}_{trail_pct or trail_usd}"

        self.active_trails[trail_id] = {
            "symbol": symbol,
            "side": side.upper(),
            "trail_pct": trail_pct,
            "trail_usd": trail_usd,
            "quantity": quantity,
            "order_id": order_id,
            "triggered": False,
            "ref_price": None,
            "current_stop_price": None,
        }

        logging.info(f"[TRAIL] Added trailing stop {trail_id} for {symbol} {side}")
        return trail_id

    async def run(self) -> None:
        """Main trailing stop management loop."""
        logging.info(f"[TRAIL] Trailing daemon started with {self.interval}s interval")

        while True:
            try:
                for trail_id, trail in list(self.active_trails.items()):
                    try:
                        await self._process_trailing_stop(trail_id, trail)
                    except Exception as e:
                        logging.error(f"[TRAIL] Error processing {trail_id}: {e}")

            except Exception as e:
                logging.warning(f"[TRAIL] Main loop error: {e}")

            await asyncio.sleep(self.interval)

    async def _process_trailing_stop(self, trail_id: str, trail: Dict[str, Any]) -> None:
        """Process a single trailing stop."""
        symbol = trail["symbol"]
        side = trail["side"]

        # Get current price
        venue = symbol.split(".")[1]
        ven_client = get_venue(venue).client
        current_price = ven_client.get_last_price(symbol)

        if not current_price:
            return  # Skip if no price

        # Initialize reference price
        if trail["ref_price"] is None:
            trail["ref_price"] = current_price
            logging.info(f"[TRAIL] {trail_id} initialized at ref_price ${current_price:.4f}")
            return

        # Calculate trailing adjustment
        ref_price = trail["ref_price"]

        if side == "BUY":
            # For long positions, trail below current price
            pct_change = (ref_price - current_price) / ref_price * 100
            trail_threshold = trail["trail_pct"] or (trail["trail_usd"] / current_price * 100)

            if pct_change >= trail_threshold:
                # Price moved up significantly, trail upward
                new_ref = current_price
                trail["ref_price"] = new_ref
                logging.info(
                    f"[TRAIL] {trail_id} adjusted UP to ${new_ref:.4f} (+{pct_change:.2f}%)"
                )
        else:  # SELL
            # For short positions, trail above current price
            pct_change = (current_price - ref_price) / ref_price * 100
            trail_threshold = trail["trail_pct"] or (trail["trail_usd"] / current_price * 100)

            if pct_change >= trail_threshold:
                # Price moved down significantly, trail downward
                new_ref = current_price
                trail["ref_price"] = new_ref
                logging.info(
                    f"[TRAIL] {trail_id} adjusted DOWN to ${new_ref:.4f} (-{pct_change:.2f}%)"
                )

        # Check stop trigger
        if not trail["triggered"]:
            trigger_price = self._calculate_stop_price(trail, current_price)

            if self._should_trigger_stop(trail, current_price, trigger_price):
                trail["triggered"] = True

                # Place the actual stop order
                stop_result = place_order(
                    symbol=symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    order_type="STOP",
                    stop_price=trigger_price,
                    quantity=trail["quantity"],
                )

                logging.info(f"[TRAIL] {trail_id} TRIGGERED stop at ${trigger_price:.4f}")
                logging.info(f"[TRAIL] Stop order placed: {stop_result}")

                # Remove trail (could keep for new stops but keeps simple)
                del self.active_trails[trail_id]

    def _calculate_stop_price(self, trail: Dict[str, Any], current_price: float) -> float:
        """Calculate where the stop should be placed."""
        if trail["side"] == "BUY":
            # For long positions, stop below current price
            if trail["trail_pct"]:
                return current_price * (1 - trail["trail_pct"] / 100)
            else:
                return current_price - trail["trail_usd"]
        else:
            # For short positions, stop above current price
            if trail["trail_pct"]:
                return current_price * (1 + trail["trail_pct"] / 100)
            else:
                return current_price + trail["trail_usd"]

    def _should_trigger_stop(
        self, trail: Dict[str, Any], current_price: float, stop_price: float
    ) -> bool:
        """Determine if stop should trigger based on current conditions."""
        if trail["side"] == "BUY":
            # For long positions, trigger when price drops to stop level
            return current_price <= stop_price
        else:
            # For short positions, trigger when price rises to stop level
            return current_price >= stop_price

    def remove_trailing_stop(self, trail_id: str) -> bool:
        """Remove a trailing stop."""
        if trail_id in self.active_trails:
            del self.active_trails[trail_id]
            logging.info(f"[TRAIL] Removed trailing stop {trail_id}")
            return True
        return False

    def list_active_trails(self) -> Dict[str, Dict[str, Any]]:
        """List all active trailing stops."""
        return self.active_trails.copy()


# Global instances for startup
_oco_task = None
_trailing_daemon = None


async def start_order_intelligence() -> None:
    """Start all order intelligence daemons."""
    global _oco_task, _trailing_daemon

    # Start OCO watcher
    _oco_task = asyncio.create_task(oco_watcher())
    logging.info("[ORDER_INTEL] OCO watcher started")

    # Start trailing stop daemon
    _trailing_daemon = TrailingDaemon()
    asyncio.create_task(_trailing_daemon.run())
    logging.info("[ORDER_INTEL] Trailing stop daemon started")


async def stop_order_intelligence() -> None:
    """Stop all order intelligence daemons."""
    global _oco_task, _trailing_daemon

    if _oco_task and not _oco_task.done():
        _oco_task.cancel()
        try:
            await _oco_task
        except asyncio.CancelledError:
            pass
        logging.info("[ORDER_INTEL] OCO watcher stopped")

    _trailing_daemon = None
    logging.info("[ORDER_INTEL] Trailing daemon cleared")
