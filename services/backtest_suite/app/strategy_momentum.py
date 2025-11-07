from typing import Dict, Any, Optional
from .strategy_base import Strategy


class MomentumBreakout(Strategy):
    def __init__(self, instrument: str):
        super().__init__("momentum_breakout", instrument)
        self._window = []

    def on_bar(self, bar: Dict[str, Any], params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        lb = int(params.get("lookback", 60))
        thr = float(params.get("breakout_z", 2.0))
        self._window.append(bar["close"])
        if len(self._window) < lb + 1:
            return None
        window = self._window[-lb:]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / max(1, len(window) - 1)
        std = var**0.5
        z = (bar["close"] - mean) / (std if std > 0 else 1.0)
        if z > thr:
            return {"side": "buy", "qty": 1.0, "price": bar["close"], "tag": "bo_long"}
        if z < -thr:
            return {
                "side": "sell",
                "qty": 1.0,
                "price": bar["close"],
                "tag": "bo_short",
            }
        return None
