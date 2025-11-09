"""
FillsListener — emits BUS 'trade.fill' for WS execution reports.

Safe to run alongside router's synchronous emitter; use EXEC_FILLS_LISTENER_ENABLED
to gate wiring in app. Designed against a generic Binance-like schema.
"""

from __future__ import annotations

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class FillsListener:
    def __init__(self, ws_client, bus, log):
        self.ws = ws_client
        self.bus = bus
        self.log = log

    async def run(self) -> None:
        async for upd in self.ws.order_updates():
            try:
                event = getattr(upd, "event", "")
                ex_type = getattr(upd, "execution_type", getattr(upd, "current_execution_type", ""))
                if event == "executionReport" and ex_type in ("TRADE", "FILL"):
                    payload = {
                        "ts": float(getattr(upd, "event_time", 0)) / 1000.0,
                        "symbol": getattr(upd, "symbol", ""),
                        "side": getattr(upd, "side", ""),
                        "venue": getattr(upd, "venue", "futures"),
                        "intent": getattr(upd, "intent", "GENERIC"),
                        "order_id": getattr(upd, "order_id", None),
                        "filled_qty": float(getattr(upd, "last_filled_qty", 0.0) or 0.0),
                        "avg_price": float(getattr(upd, "last_filled_price", 0.0) or 0.0),
                    }
                    self.bus.fire("trade.fill", payload)
            except _SUPPRESSIBLE_EXCEPTIONS:
                self.log.exception("[FILLS-WS] update handling error")
