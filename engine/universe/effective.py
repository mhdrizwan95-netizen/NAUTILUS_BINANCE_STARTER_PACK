"""Effective universe for strategy subscriptions."""

from __future__ import annotations

import os
from typing import Any, List


class StrategyUniverse:
    """Represents a trading universe for a strategy.
    
    Integrates with SymbolScanner for dynamic symbol selection, falling back
    to environment variables when scanner is unavailable.
    """
    
    def __init__(self, scanner: Any | None = None):
        """Initialize with optional scanner.
        
        Args:
            scanner: Optional SymbolScanner instance for dynamic universe.
        """
        self.scanner = scanner
    
    def get(self, kind: str) -> List[str]:
        """Get symbols for a specific strategy kind.
        
        Priority:
        1. Scanner's dynamic selection (if scanner provided and has symbols)
        2. {KIND}_SYMBOLS environment variable
        3. STRATEGY_SYMBOLS environment variable
        4. TRADE_SYMBOLS environment variable
        
        Args:
            kind: Strategy type identifier (e.g., 'scalp', 'trend', 'momentum_rt')
            
        Returns:
            List of symbol strings (e.g., ['BTCUSDT', 'ETHUSDT'])
        """
        # Priority 1: Use scanner if available and has selections
        if self.scanner is not None:
            try:
                # SymbolScanner.current_universe() or get_selected()
                if hasattr(self.scanner, 'current_universe'):
                    selected = self.scanner.current_universe(kind)
                elif hasattr(self.scanner, 'get_selected'):
                    selected = self.scanner.get_selected()
                else:
                    selected = None
                    
                if selected and len(selected) > 0:
                    return list(selected)
            except Exception:
                # Fail silently to env var fallback
                pass
        
        # Priority 2-4: Fallback to environment variables
        env_key = f"{kind.upper()}_SYMBOLS"
        raw = os.getenv(env_key) or os.getenv("STRATEGY_SYMBOLS") or os.getenv("TRADE_SYMBOLS") or ""
        
        symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
        return symbols
    
    def is_scanner_active(self) -> bool:
        """Check if scanner is actively providing symbols."""
        if self.scanner is None:
            return False
        try:
            if hasattr(self.scanner, 'get_selected'):
                return len(self.scanner.get_selected()) > 0
        except Exception:
            pass
        return False

    def __repr__(self):
        active = "active" if self.is_scanner_active() else "inactive"
        return f"StrategyUniverse(scanner={active})"

