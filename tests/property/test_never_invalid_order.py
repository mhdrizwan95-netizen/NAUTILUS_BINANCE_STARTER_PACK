import asyncio
from dataclasses import dataclass

import hypothesis.strategies as st
from hypothesis import given, settings as hyp_settings

from engine.core.order_router import _place_market_order_async_core, set_exchange_client
from engine.core.venue_specs import SymbolSpec


@dataclass
class _StubFilter:
    step_size: float
    min_qty: float
    min_notional: float
    tick_size: float = 0.0


class _StubBinanceClient:
    def __init__(self, px: float, spec: SymbolSpec):
        self._px = float(px)
        self._spec = spec
        self.last_submitted_qty = None
        self.last_symbol = None

    async def ticker_price(self, symbol: str, *, market: str | None = None):
        return self._px

    async def exchange_filter(self, symbol: str, *, market: str | None = None):
        return _StubFilter(
            step_size=self._spec.step_size,
            min_qty=self._spec.min_qty,
            min_notional=self._spec.min_notional,
            tick_size=0.0,
        )

    async def submit_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market: str | None = None,
        reduce_only: bool = False,
    ):
        # capture for assertions
        self.last_submitted_qty = float(quantity)
        self.last_symbol = symbol
        return {
            "symbol": symbol,
            "executedQty": float(quantity),
            "filled_qty_base": float(quantity),
            "avg_fill_price": self._px,
            "status": "FILLED",
        }


@hyp_settings(deadline=None, max_examples=50)
@given(
    quote_usd=st.floats(
        min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
    step=st.sampled_from([1e-6, 1e-5, 1e-4, 1e-3]),
    min_qty=st.sampled_from([0.0, 1e-6, 1e-5, 1e-4, 1e-3]),
    min_notional=st.sampled_from([0.0, 5.0, 10.0, 50.0]),
)
def test_never_submit_invalid_size_for_symbol(quote_usd, step, min_qty, min_notional):
    """Property: router never submits a qty below min_qty nor below min_notional."""
    px = 50_000.0  # stable price for BTCUSDT
    spec = SymbolSpec(
        min_qty=float(min_qty), step_size=float(step), min_notional=float(min_notional)
    )
    client = _StubBinanceClient(px=px, spec=spec)
    set_exchange_client("BINANCE", client)

    async def run():
        try:
            res = await _place_market_order_async_core(
                symbol="BTCUSDT.BINANCE",
                side="BUY",
                quote=float(quote_usd),
                quantity=None,
                portfolio=None,
            )
        except Exception:
            # Expected for quotes below min_notional or quantization to zero
            return
        # If placed, quantity must satisfy min_qty and min_notional
        q = float(res.get("filled_qty_base") or 0.0)
        assert q >= spec.min_qty - 1e-12
        assert (q * px) >= spec.min_notional - 1e-6

    asyncio.run(run())
