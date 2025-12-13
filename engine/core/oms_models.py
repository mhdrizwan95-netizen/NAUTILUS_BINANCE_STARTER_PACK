from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

def new_order_id() -> str:
    """Generate a unique order ID."""
    return str(uuid.uuid4())

@dataclass
class OrderRecord:
    """
    Uniform internal representation of an order in the OMS.
    """
    id: str
    client_key: str
    symbol: str  # e.g. BTCUSDT.BINANCE
    side: str  # BUY/SELL
    order_type: str  # MARKET, LIMIT, etc.
    quantity: float
    
    # Optional / Lifecycle fields
    price: Optional[float] = None
    stop_price: Optional[float] = None
    tif: str = "GTC"
    status: str = "NEW"
    venue_order_id: Optional[str] = None
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    error: Optional[str] = None
    
    # Metadata
    strategy_id: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
