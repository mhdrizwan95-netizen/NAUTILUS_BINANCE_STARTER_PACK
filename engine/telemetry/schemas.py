"""
Telemetry Schemas
Shared Pydantic models for WebSocket telemetry between Engine and Frontend.
Mirrors frontend/src/types/trading.ts
"""
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class GlobalMetrics(BaseModel):
    equity: float
    cash: float
    pnl_realized: float
    pnl_unrealized: float
    open_positions_count: int
    daily_return_pct: float
    win_rate: float
    max_drawdown: float

class StrategyPerformance(BaseModel):
    id: str
    name: str
    symbol: str
    pnl_realized: float
    pnl_unrealized: float
    position_size: float
    confidence: float
    signal: float  # -1.0 to 1.0
    status: str  # "active", "paused", "error"

class VenueStatus(BaseModel):
    name: str
    status: str  # "connected", "disconnected", "degraded"
    latency_ms: float
    rate_limit_usage: float  # 0-100%

class TradeEvent(BaseModel):
    id: str
    symbol: str
    side: str  # "BUY", "SELL"
    quantity: float
    price: float
    fee: float
    timestamp: int
    pnl: Optional[float] = None

class TelemetryPayload(BaseModel):
    type: str  # "metrics", "performances", "venues", "trade"
    data: Any
    timestamp: int
