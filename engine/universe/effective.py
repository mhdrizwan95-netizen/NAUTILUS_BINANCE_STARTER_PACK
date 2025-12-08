"""Effective universe for strategy subscriptions."""

from __future__ import annotations

from typing import List


import os
from typing import List, Any

class StrategyUniverse:
    """Represents a trading universe for a strategy."""
    
    def __init__(self, scanner: Any | None = None):
        """Initialize with optional scanner."""
        self.scanner = scanner
    
    def get(self, kind: str) -> List[str]:
        """Get symbols for a specific strategy kind."""
        # TODO: Integrate with scanner if available
        
        # Fallback to environment variables
        # Priority: {KIND}_SYMBOLS > STRATEGY_SYMBOLS > TRADE_SYMBOLS
        env_key = f"{kind.upper()}_SYMBOLS"
        raw = os.getenv(env_key) or os.getenv("STRATEGY_SYMBOLS") or os.getenv("TRADE_SYMBOLS") or ""
        
        symbols = [s.strip() for s in raw.split(",") if s.strip()]
        return symbols

    def __repr__(self):
        return f"StrategyUniverse(scanner={self.scanner})"
