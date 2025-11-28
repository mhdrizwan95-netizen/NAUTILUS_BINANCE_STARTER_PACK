from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from ops.engine_client import market_order
from ops.idempotency import reserve_idempotency, store_response
from ops.middleware.control_guard import ControlContext, IdempotentGuard

router = APIRouter()
_REQUEST_ERRORS = (RuntimeError, ValueError, ConnectionError)
IdemGuardDep = Annotated[ControlContext, Depends(IdempotentGuard)]


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
        description="Optional trading venue override (default BINANCE). "
        "Legacy venues have been removed; omit unless explicitly routing to a Binance variant.",
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
async def create_market_order(body: MarketOrderIn, guard: IdemGuardDep):
    idem_key = guard.idempotency_key
    with reserve_idempotency(idem_key):
        try:
            result = await market_order(body.payload())
        except _REQUEST_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store_response(idem_key, result if isinstance(result, dict) else {"result": result})
        return result
