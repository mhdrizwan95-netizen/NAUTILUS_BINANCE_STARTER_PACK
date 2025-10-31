
from typing import Optional, Dict, Any
from loguru import logger

class BaseStrategy:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.model = None
    def bind_model(self, m): self.model = m
    def decide(self, now, row): raise NotImplementedError
    def observe_outcome(self, trade): pass

class MomentumBreakout(BaseStrategy):
    def __init__(self, symbol: str, lookback: int = 60):
        super().__init__(symbol)
        self.lookback = lookback
    def decide(self, now, row):
        if self.model is None: return None
        edge = self.model.regime_edge(row)
        return {"symbol": self.symbol, "edge": edge, "params": {"lookback": self.lookback}, "features": {}}

class MeanReversion(BaseStrategy):
    def __init__(self, symbol: str, z_entry: float = 1.0):
        super().__init__(symbol)
        self.z_entry = z_entry
    def decide(self, now, row):
        if self.model is None: return None
        edge = -self.model.regime_edge(row)
        return {"symbol": self.symbol, "edge": edge, "params": {"z_entry": self.z_entry}, "features": {}}
