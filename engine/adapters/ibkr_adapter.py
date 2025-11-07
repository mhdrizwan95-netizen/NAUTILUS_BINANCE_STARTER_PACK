"""
IBKR venue adapter for the multi-venue engine.

Provides IBKR-specific implementation of VenueClient protocol.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.connectors.ibkr_client import IbkrClient


class IbkrVenue:
    """IBKR venue adapter implementing VenueClient protocol."""

    VENUE = "IBKR"

    def __init__(self, client: IbkrClient):
        self._c = client
        logging.info(f"[IBKR Venue] Initialized with client: {client}")

    def get_last_price(self, symbol: str) -> float | None:
        """Get latest price for IBKR symbol."""
        # Strip venue suffix if present
        clean_symbol = symbol.split(".")[0] if "." in symbol else symbol
        return self._c.get_last_price(clean_symbol)

    def place_market_order(
        self, *, symbol: str, side: str, quote: float | None, quantity: float | None
    ) -> dict[str, Any]:
        """Place market order via IBKR. Only supports quantity (integer shares)."""
        if quote is not None:
            raise ValueError("QUOTE_UNSUPPORTED: IBKR router must convert quote to integer shares")

        clean_symbol = symbol.split(".")[0] if "." in symbol else symbol
        quantity_int = int(quantity or 0)

        result = self._c.place_market_order(symbol=clean_symbol, side=side, quantity=quantity_int)

        # Add venue info
        result["venue"] = self.VENUE
        return result

    def account_snapshot(self) -> dict[str, Any]:
        """IBKR account snapshot (minimal implementation)."""
        return {
            "venue": self.VENUE,
            "equity_usd": None,  # Would integrate with IBKR account data
            "cash_usd": None,
            "pnl": {"realized": None, "unrealized": None},
        }

    def positions(self) -> list[dict[str, Any]]:
        """IBKR positions. Source of truth is engine state, not here."""
        return []

    def list_open_orders(self) -> list[dict[str, Any]]:
        """List open orders for IBKR reconciliation."""
        try:
            orders = self._c.ib.openOrders()
            return [
                {
                    "order_id": str(o.orderId),
                    "symbol": o.contract.symbol,
                    "side": o.action,
                    "type": o.orderType,
                    "price": o.l_auxPrice or o.lmtPrice or 0.0,
                    "stop_price": o.auxPrice if o.orderType.startswith("STP") else 0.0,
                    "origQty": o.totalQuantity,
                    "executedQty": 0.0,  # IBKR doesn't expose partial fills easily
                    "status": "Submitted",  # IBKR openOrders are active
                    "timeInForce": o.tif or "GTC",
                }
                for o in orders
            ]
        except Exception as e:
            logging.warning(f"[IBKR] Failed to list open orders: {e}")
            return []
