# engine/connectors/ibkr_client.py
from __future__ import annotations

import logging
import os

from ib_insync import IB, MarketOrder, Stock

try:
    from ib_insync.util import IBError
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    IBError = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)
IBKR_BASE_EXCEPTIONS: tuple[type[Exception], ...] = (
    RuntimeError,
    ValueError,
    ConnectionError,
    TimeoutError,
    OSError,
)
IBKR_CLIENT_ERRORS: tuple[type[Exception], ...] = (
    IBKR_BASE_EXCEPTIONS + (IBError,) if IBError is not None else IBKR_BASE_EXCEPTIONS
)


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOGGER.warning("[IBKR Client] %s: %s", context, exc, exc_info=True)


def _enabled() -> bool:
    return os.getenv("IBKR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


class IbkrClientDisabledError(RuntimeError):
    """Raised when the IBKR client is instantiated while disabled."""

    def __init__(self) -> None:
        super().__init__("IBKR client disabled. Set IBKR_ENABLED=true to initialize.")


class IbkrOrderError(ValueError):
    """Raised when IBKR order placement fails."""

    def __init__(self) -> None:
        super().__init__("IBKR_ORDER_FAILED: order failed")


class IbkrClient:
    def __init__(self):
        if not _enabled():
            raise IbkrClientDisabledError()
        self.ib: IB | None = None
        self._connected = False
        host = os.getenv("IBKR_HOST", "127.0.0.1")
        port = int(os.getenv("IBKR_PORT", "7497"))
        client_id = int(os.getenv("IBKR_CLIENT_ID", "777"))
        try:
            self.ib = IB()
            self.ib.connect(host, port, clientId=client_id, readonly=False)
            self._connected = True
        except IBKR_CLIENT_ERRORS:
            _LOGGER.exception(
                "IBKR connection failed (OK for startup) host=%s port=%s client_id=%s",
                host,
                port,
                client_id,
            )
            self._connected = False

    def _to_contract(self, symbol: str):
        # Accept "AAPL" or "AAPL.IBKR"
        base = symbol.split(".")[0].upper()
        # Default SMART routing, USD
        return Stock(base, "SMART", "USD")

    def get_last_price(self, symbol: str) -> float | None:
        if not self._connected or not self.ib:
            return None
        try:
            c = self._to_contract(symbol)
            cd = self.ib.reqMktData(c, "", False, False)
            # wait briefly for tick
            self.ib.sleep(0.25)
            px = cd.last if cd.last else cd.close
            try:
                self.ib.cancelMktData(c)
            except IBKR_CLIENT_ERRORS as cancel_exc:
                _log_suppressed("cancel market data", cancel_exc)
            return float(px) if px else None
        except IBKR_CLIENT_ERRORS:
            _LOGGER.exception("IBKR get_last_price error for symbol=%s", symbol)
            return None

    def place_market_order(self, *, symbol: str, side: str, quote=None, quantity=None):
        """
        quantity must be integer shares; quote ignored here (router pre-computes quantity)
        """
        if not self._connected or not self.ib:
            raise ValueError("IBKR_NOT_CONNECTED", "IBKR client is not connected")
        if quote:
            raise ValueError(
                "QUOTE_UNSUPPORTED",
                "Router must convert quote→quantity for IBKR equities.",
            )
        if quantity is None or int(quantity) != quantity:
            raise ValueError(
                "QTY_INTEGER_REQUIRED", "IBKR equities require integer share quantity."
            )
        try:
            c = self._to_contract(symbol)
            action = "BUY" if side.upper() == "BUY" else "SELL"
            qty_int = int(quantity)
            order = MarketOrder(action, qty_int)
            trade = self.ib.placeOrder(c, order)
            # wait for fill or ack
            self.ib.sleep(0.1)
            self.ib.waitOnUpdate(timeout=5)
            avg = float(trade.orderStatus.avgFillPrice or 0.0)
            filled = int(trade.orderStatus.filled or 0)
        except IBKR_CLIENT_ERRORS as exc:
            _LOGGER.exception(
                "IBKR place_market_order error symbol=%s side=%s quantity=%s",
                symbol,
                side,
                quantity,
            )
            raise IbkrOrderError() from exc
        else:
            return {
                "avg_fill_price": avg,
                "filled_qty_base": filled,
                "order_id": trade.order.orderId,
                "status": trade.orderStatus.status,
            }

    def get_contract_details(self, symbol: str):
        if not self._connected or not self.ib:
            return None
        try:
            c = self._to_contract(symbol)
            return self.ib.reqContractDetails(c)
        except IBKR_CLIENT_ERRORS:
            _LOGGER.exception("IBKR get_contract_details error for symbol=%s", symbol)
            return None
