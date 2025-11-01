from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from ops.engine_client import market_order

router = APIRouter()


class MarketOrderIn(BaseModel):
    symbol: str = Field(..., example="BTCUSDT.BINANCE")
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
            raise ValueError("Provide exactly one of quote or quantity.")
        return self

    def payload(self) -> dict:
        base = {
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
async def create_market_order(body: MarketOrderIn):
    try:
        result = await market_order(body.payload())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
