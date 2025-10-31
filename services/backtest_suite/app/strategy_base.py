
from typing import Dict, Any, Optional

class Strategy:
    def __init__(self, name: str, instrument: str):
        self.name = name
        self.instrument = instrument

    def on_bar(self, bar: Dict[str, Any], params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Return an order dict or None.
        Order example: { "side": "buy", "qty": 1.0, "price": bar["close"], "tag": "...", "stop": price, "tp": price }
        """
        return None
