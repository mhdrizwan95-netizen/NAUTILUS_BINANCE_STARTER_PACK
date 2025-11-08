"""
Order Management System (OMS) data models and types.

Defines the complete order lifecycle from creation to terminal state.
"""

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

# Type definitions for better type safety
OrderType = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
OrderStatus = Literal["NEW", "SUBMITTED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED"]
OrderSide = Literal["BUY", "SELL"]
TimeInForce = Literal["GTC", "DAY", "IOC", "FOK"]


@dataclass
class OrderRecord:
    """
    Complete order lifecycle record.

    Tracks an order from creation through all state changes until terminal.
    """

    id: str
    client_key: str  # X-Idempotency-Key or auto-generated
    symbol: str  # BASE.VENUE format (e.g., "AAPL.IBKR")
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None  # Limit price or stop-limit limit price
    stop_price: Optional[float] = None  # Stop trigger price
    tif: TimeInForce = "GTC"  # Time in force
    status: OrderStatus = "NEW"
    venue_order_id: Optional[str] = None  # Venue-specific order ID
    oco_group_id: Optional[str] = None  # OCO (one cancels other) group identifier
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    fee_usd: float = 0.0
    created_ms: int = 0
    updated_ms: int = 0
    additional_data: Optional[Dict[str, Any]] = None  # Extension field

    def __post_init__(self):
        """Initialize timestamps if not provided."""
        now_ms = int(time.time() * 1000)
        if self.created_ms == 0:
            self.created_ms = now_ms
        if self.updated_ms == 0:
            self.updated_ms = now_ms

    @property
    def is_terminal(self) -> bool:
        """Check if order is in terminal state and can be cleaned up."""
        return self.status in ("FILLED", "CANCELED", "REJECTED")

    @property
    def remaining_qty(self) -> float:
        """Calculate remaining unfilled quantity."""
        return self.quantity - self.filled_qty

    def update_fill(self, filled_qty: float, avg_price: float, fee: float = 0.0) -> None:
        """Update order with a fill event."""
        self.filled_qty = filled_qty
        self.avg_fill_price = avg_price
        self.fee_usd = fee
        self.updated_ms = int(time.time() * 1000)

        # Status progression
        if self.filled_qty >= self.quantity:
            self.status = "FILLED"
        elif self.filled_qty > 0:
            self.status = "PARTIALLY_FILLED"

    def mark_submitted(self, venue_order_id: str) -> None:
        """Mark order as submitted to venue."""
        self.status = "SUBMITTED"
        self.venue_order_id = venue_order_id
        self.updated_ms = int(time.time() * 1000)

    def mark_terminal(self, status: OrderStatus) -> None:
        """Mark order as terminal (filled, canceled, rejected)."""
        self.status = status
        self.updated_ms = int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderRecord":
        """Create from dictionary (deserialization)."""
        return cls(**data)


def new_order_id() -> str:
    """Generate unique order identifier."""
    return uuid.uuid4().hex


def generate_idempotency_key() -> str:
    """Generate idempotency key for order deduplication."""
    return f"idemp_{uuid.uuid4().hex}"
