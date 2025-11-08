"""
State Synchronization & Recovery Layer.

Maintains fidelity between local OMS state and live venue truth.
Reconciles discrepancies automatically on boot and continuously during runtime.
"""

import asyncio
import logging
from typing import Any, Dict

from ..metrics import REGISTRY
from .oms_models import OrderRecord, new_order_id
from .oms_store import OMSStore
from .venues import get_venue, list_venues

_oms = OMSStore()
_reconcile_runs = REGISTRY.metric("reconcile_runs_total", "Total reconciliation runs", "counter")
_reconcile_imported = REGISTRY.metric(
    "reconcile_imported_total", "Orders imported during reconciliation", "counter"
)
_reconcile_closed = REGISTRY.metric(
    "reconcile_closed_total", "Orders closed during reconciliation", "counter"
)


async def reconcile_loop(interval: int = 30) -> None:
    """
    Continuous reconciliation daemon that maintains OMS truth.

    Args:
        interval: Sync interval in seconds (default 30s)
    """
    logging.info("[SYNC] Reconciliation daemon started (interval=%ds)", interval)

    while True:
        try:
            await _perform_reconciliation()
            _reconcile_runs.inc()
            await asyncio.sleep(interval)

        except Exception as e:
            logging.warning("[SYNC] Reconciliation error: %s", e)
            await asyncio.sleep(interval)


async def _perform_reconciliation() -> None:
    """
    Core reconciliation logic between local OMS and all connected venues.
    """
    try:
        local_open = list(_oms.list_open())

        for venue in list_venues():
            ven_client = get_venue(venue).client

            # Skip venues without reconciliation support
            if not hasattr(ven_client, "list_open_orders"):
                logging.debug("[SYNC] Skipping %s - no list_open_orders support", venue)
                continue

            try:
                # Fetch remote open orders
                remote_orders = ven_client.list_open_orders()

                # Create lookup maps
                remote_by_id = {str(order["order_id"]): order for order in remote_orders}

                # Process local orders for this venue
                for order_rec in local_open:
                    order_venue = order_rec.symbol.split(".")[1]
                    if order_venue != venue:
                        continue

                    # Check if this local order still exists remotely
                    remote_match = None
                    if order_rec.venue_order_id in remote_by_id:
                        remote_match = remote_by_id[order_rec.venue_order_id]
                    else:
                        # Try to find by symbol/side match (more heuristic)
                        for remote in remote_orders:
                            if (
                                remote.get("symbol") == order_rec.symbol.split(".")[0]
                                and remote.get("side") == order_rec.side
                            ):
                                remote_match = remote
                                break

                    if not remote_match:
                        # Local order missing remotely - likely filled or canceled
                        _oms.close(order_rec.id, "FILLED")  # Assume filled for safety
                        _reconcile_closed.inc()
                        logging.info("[SYNC] Closed %s (missing remotely)", order_rec.symbol)

                # Check for remote orders not in local OMS (import them)
                local_venue_orders = {
                    ord.venue_order_id: ord
                    for ord in local_open
                    if ord.symbol.split(".")[1] == venue
                }

                for remote_order in remote_orders:
                    remote_id = str(remote_order["order_id"])
                    if remote_id not in local_venue_orders:
                        # Found remote order not in local OMS - import it
                        await _import_remote_order(remote_order, venue)

            except Exception as ven_e:
                logging.warning("[SYNC] Venue %s reconciliation failed: %s", venue, ven_e)

        # Persist updated OMS state
        _oms._persist()

    except Exception as e:
        logging.error("[SYNC] Reconciliation failure: %s", e)


async def _import_remote_order(remote_order: Dict[str, Any], venue: str) -> None:
    """
    Import an externally placed order into local OMS.

    Args:
        remote_order: Remote order data from venue
        venue: Venue identifier
    """
    try:
        # Map remote order data to local OrderRecord
        symbol = f"{remote_order['symbol']}.{venue}"

        # Determine order type (default to LIMIT for robustness)
        order_type = remote_order.get("type", "LIMIT").upper()
        if order_type not in ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]:
            order_type = "LIMIT"

        # Extract quantities and prices
        orig_qty = float(remote_order.get("origQty", remote_order.get("quantity", 0.0)))
        executed_qty = float(remote_order.get("executedQty", 0.0))

        record = OrderRecord(
            id=new_order_id(),
            client_key="imported",  # Mark as imported
            symbol=symbol,
            side=remote_order.get("side", "BUY").upper(),
            order_type=order_type,
            quantity=orig_qty,
            price=float(remote_order.get("price", 0.0)) or None,
            stop_price=float(remote_order.get("stop_price", 0.0)) or None,
            tif=remote_order.get("timeInForce", "GTC"),
            status=remote_order.get("status", "NEW").upper(),
            venue_order_id=str(remote_order["order_id"]),
            filled_qty=executed_qty,
            avg_fill_price=float(remote_order.get("avg_fill_price", 0.0)) or None,
        )

        _oms.upsert(record, "SYNC_IMPORT")
        _reconcile_imported.inc()

        logging.info(
            "[SYNC] Imported remote order: %s (%s) for %s",
            remote_order["order_id"],
            record.side,
            symbol,
        )

    except Exception as e:
        logging.error(
            "[SYNC] Failed to import remote order %s: %s",
            remote_order.get("order_id"),
            e,
        )


async def reconcile_once() -> Dict[str, int]:
    """
    Perform a single reconciliation run.

    Returns:
        Dict with reconciliation statistics
    """
    before_imported = _reconcile_imported.collect()[0].samples[0].value
    before_closed = _reconcile_closed.collect()[0].samples[0].value

    await _perform_reconciliation()

    after_imported = _reconcile_imported.collect()[0].samples[0].value
    after_closed = _reconcile_closed.collect()[0].samples[0].value

    return {
        "imported": int(after_imported - before_imported),
        "closed": int(after_closed - before_closed),
    }


def clear_reconciliation_metrics() -> None:
    """Reset reconciliation metrics (for testing)."""
    _reconcile_runs.clear()
    _reconcile_imported.clear()
    _reconcile_closed.clear()
