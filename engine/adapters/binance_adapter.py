"""
Binance venue adapter for the multi-venue engine.

Provides Binance-specific implementation of VenueClient protocol.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

try:
    from binance.error import BinanceAPIException, BinanceRequestException
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    BinanceAPIException = None  # type: ignore[assignment]
    BinanceRequestException = None  # type: ignore[assignment]

BINANCE_ERRORS: tuple[type[Exception], ...] = tuple(
    err for err in (BinanceAPIException, BinanceRequestException) if err is not None
)

logger = logging.getLogger(__name__)


def _log_suppressed(context: str, err: Exception) -> None:
    logger.warning("[Binance Venue] %s: %s", context, err, exc_info=True)


class BinanceVenue:
    """Binance venue adapter implementing VenueClient protocol."""

    VENUE = "BINANCE"

    def __init__(self, client):
        self._c = client
        logging.info(f"[Binance Venue] Initialized with client: {client}")

    def get_last_price(self, symbol: str) -> float | None:
        """Get latest price for Binance symbol."""
        # Strip venue suffix if present
        clean_symbol = symbol.split(".")[0] if "." in symbol else symbol
        return self._c.get_last_price(clean_symbol)

    def place_market_order(
        self, *, symbol: str, side: str, quote: float | None, quantity: float | None
    ) -> dict[str, Any]:
        """Place market order via Binance. Supports both quote and quantity."""
        clean_symbol = symbol.split(".")[0] if "." in symbol else symbol

        result = self._c.place_market_order(
            symbol=clean_symbol, side=side, quote=quote, quantity=quantity
        )

        # Add venue info
        result["venue"] = self.VENUE
        return result

    def account_snapshot(self) -> dict[str, Any]:
        """Binance account snapshot."""
        try:
            return self._c.account_snapshot()
        except (*BINANCE_ERRORS, httpx.HTTPError, ValueError, KeyError) as exc:
            _log_suppressed("account snapshot failed", exc)
        return {
            "venue": self.VENUE,
            "equity_usd": None,
            "cash_usd": None,
            "pnl": {"realized": None, "unrealized": None},
        }

    def positions(self) -> list[dict[str, Any]]:
        """Binance positions."""
        try:
            return self._c.positions()
        except (*BINANCE_ERRORS, httpx.HTTPError, ValueError, KeyError) as exc:
            _log_suppressed("positions fetch failed", exc)
        return []

    def list_open_orders(self) -> list[dict[str, Any]]:
        """List open orders for Binance reconciliation."""
        try:
            orders = self._c.get_open_orders()
        except (*BINANCE_ERRORS, httpx.HTTPError, ValueError, KeyError) as exc:
            _log_suppressed("list open orders failed", exc)
            return []
        return [
            {
                "order_id": str(o["orderId"]),
                "symbol": o["symbol"],
                "side": o["side"],
                "type": o["type"],
                "price": float(o.get("price", 0.0)),
                "stop_price": float(o.get("stopPrice", 0.0)),
                "origQty": float(o.get("origQty", 0.0)),
                "executedQty": float(o.get("executedQty", 0.0)),
                "status": o.get("status"),
                "timeInForce": o.get("timeInForce", "GTC"),
            }
            for o in orders
        ]
