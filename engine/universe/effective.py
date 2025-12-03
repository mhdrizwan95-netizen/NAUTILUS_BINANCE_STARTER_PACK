"""Effective universe for strategy subscriptions."""

from __future__ import annotations

from typing import List


class StrategyUniverse:
    """Represents a trading universe for a strategy."""
    
    def __init__(self, symbols: List[str] | None = None):
        """Initialize strategy universe with symbols."""
        self.symbols = symbols or []
    
    def __iter__(self):
        """Allow iteration over symbols."""
        return iter(self.symbols)
    
    def __len__(self):
        """Return number of symbols."""
        return len(self.symbols)
    
    def __repr__(self):
        """String representation."""
        return f"StrategyUniverse({self.symbols})"
