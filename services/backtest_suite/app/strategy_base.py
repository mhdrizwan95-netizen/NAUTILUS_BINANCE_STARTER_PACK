from typing import Any


class Strategy:
    def __init__(self, name: str, instrument: str):
        self.name = name
        self.instrument = instrument

    def on_bar(self, bar: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
        """
        Return an order dict or None.
        Order example: { "side": "buy", "qty": 1.0, "price": bar["close"], "tag": "...", "stop": price, "tp": price }
        """
        return None
