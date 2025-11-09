from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from ops.engine_client import market_order
from ops.ui_api import require_ops_token

router = APIRouter()
_REQUEST_ERRORS = (RuntimeError, ValueError, ConnectionError)


class QuoteOrQuantityRequired(ValueError):
    """Raised when both quote and quantity are provided (or missing)."""

    def __init__(self) -> None:
        super().__init__("Provide exactly one of quote or quantity.")


class MarketOrderIn(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT.BINANCE"])
    side: str = Field(..., pattern="^(?i)(buy|sell)$")
    quote: float | None = Field(None, gt=0)
    quantity: float | None = Field(None, gt=0)
    venue: str | None = Field(
        None,
        description="Optional trading venue override, e.g. KRAKEN. "
        "If omitted the engine falls back to its configured VENUE.",
    )

    @model_validator(mode="after")
    def check_exclusive(self):
        quote = self.quote
        qty = self.quantity
        if (quote is None and qty is None) or (quote is not None and qty is not None):
            raise QuoteOrQuantityRequired()
        return self

    def payload(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "symbol": self.symbol,
            "side": self.side.upper(),
        }
        if self.quote is not None:
            base["quote"] = self.quote
        else:
            base["quantity"] = self.quantity
        if self.venue:
            base["venue"] = self.venue.upper()
        return base


@router.post("/orders/market")
async def create_market_order(body: MarketOrderIn, _auth: None = Depends(require_ops_token)):
    try:
        result = await market_order(body.payload())
    except _REQUEST_ERRORS as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
