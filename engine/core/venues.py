"""
Central venue registry and protocol for multi-venue trading.

Provides unified interface across different exchanges (Binance crypto, IBKR traditional assets).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Optional, Dict, Any, List

class VenueClient(Protocol):
    """Unified interface that all venue adapters must implement."""

    def get_last_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol. Returns None if unavailable."""
        ...

    def place_market_order(self, *, symbol: str, side: str, quote: float | None, quantity: float | None) -> Dict[str, Any]:
        """
        Place market order.

        Args:
            symbol: Instrument identifier (BASE.VENUE format)
            side: "BUY" or "SELL"
            quote: USD quote amount (converts to quantity)
            quantity: Direct quantity/shares

        Returns:
            Dict with execution details
        """
        ...

    def account_snapshot(self) -> Dict[str, Any]:
        """Optional: Get account balances and equity."""
        return {"equity_usd": None, "cash_usd": None}

    def positions(self) -> List[Dict[str, Any]]:
        """Optional: Get current positions."""
        return []


@dataclass
class VenueEntry:
    """Registered venue with client."""
    name: str
    client: VenueClient


# Global registry
_REGISTRY: Dict[str, VenueEntry] = {}


def register_venue(name: str, client: VenueClient) -> None:
    """Register a venue adapter."""
    key = name.upper()
    _REGISTRY[key] = VenueEntry(name=key, client=client)


def get_venue(name: str) -> VenueEntry:
    """Get registered venue by name."""
    key = name.upper()
    if key not in _REGISTRY:
        available = list_venues()
        raise ValueError(f"VENUE_NOT_REGISTERED: {name}. Available: {available}")
    return _REGISTRY[key]


def list_venues() -> List[str]:
    """List all registered venue names."""
    return sorted(_REGISTRY.keys())


def is_venue_registered(name: str) -> bool:
    """Check if venue is registered."""
    return name.upper() in _REGISTRY


def clear_venues() -> None:
    """Clear all registered venues (for testing)."""
    _REGISTRY.clear()
