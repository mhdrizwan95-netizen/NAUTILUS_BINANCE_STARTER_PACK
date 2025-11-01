# engine/connectors/ibkr_client.py
from __future__ import annotations
import os
from typing import Optional
from ib_insync import IB, Stock, MarketOrder


def _enabled() -> bool:
    return os.getenv("IBKR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


class IbkrClient:
    def __init__(self):
        if not _enabled():
            raise RuntimeError(
                "IBKR client disabled. Set IBKR_ENABLED=true to initialize."
            )
        self.ib = None
        self._connected = False
        try:
            host = os.getenv("IBKR_HOST", "127.0.0.1")
            port = int(os.getenv("IBKR_PORT", "7497"))
            client_id = int(os.getenv("IBKR_CLIENT_ID", "777"))
            self.ib = IB()
            self.ib.connect(host, port, clientId=client_id, readonly=False)
            self._connected = True
        except Exception as e:
            print(f"IBKR connection failed (OK for startup): {e}")
            self._connected = False

    def _to_contract(self, symbol: str):
        # Accept "AAPL" or "AAPL.IBKR"
        base = symbol.split(".")[0].upper()
        # Default SMART routing, USD
        return Stock(base, "SMART", "USD")

    def get_last_price(self, symbol: str) -> Optional[float]:
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
            except Exception:
                pass
            return float(px) if px else None
        except Exception as e:
            print(f"IBKR get_last_price error: {e}")
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
            order = MarketOrder(action, int(quantity))
            trade = self.ib.placeOrder(c, order)
            # wait for fill or ack
            self.ib.sleep(0.1)
            self.ib.waitOnUpdate(timeout=5)
            avg = float(trade.orderStatus.avgFillPrice or 0.0)
            filled = int(trade.orderStatus.filled or 0)
            return {
                "avg_fill_price": avg,
                "filled_qty_base": filled,
                "order_id": trade.order.orderId,
                "status": trade.orderStatus.status,
            }
        except Exception as e:
            print(f"IBKR place_market_order error: {e}")
            raise ValueError("IBKR_ORDER_FAILED", f"Order failed: {e}")

    def get_contract_details(self, symbol: str):
        if not self._connected or not self.ib:
            return None
        try:
            c = self._to_contract(symbol)
            return self.ib.reqContractDetails(c)
        except Exception as e:
            print(f"IBKR get_contract_details error: {e}")
            return None
