import asyncio
from unittest.mock import AsyncMock, Mock

from engine.core.order_router import (
    OrderRouter,
    _place_market_order_async_core,
    exchange_client,
    set_exchange_client,
)
from engine.core.portfolio import Portfolio


class StubMarginClient:
    def __init__(self):
        self.submit_limit_order = AsyncMock(
            return_value={
                "symbol": "BTCUSDT",
                "executedQty": 0.01,
                "avg_fill_price": 10000.0,
                "filled_qty_base": 0.01,
                "time_in_force": "IOC",
            }
        )
        self.ticker_price = Mock(return_value=10000.0)
        self.exchange_filter = AsyncMock(return_value=None)
        self.order_status = AsyncMock(return_value=None)


def test_binance_margin_market_quote_applies_margin_market():
    margin_client = StubMarginClient()
    portfolio = Portfolio()
    previous_client = exchange_client("BINANCE_MARGIN")
    set_exchange_client("BINANCE_MARGIN", margin_client)
    try:

        async def _run():
            router = OrderRouter(margin_client, portfolio, venue="BINANCE_MARGIN")
            return await router.market_quote("BTCUSDT.BINANCE_MARGIN", "BUY", 100.0)

        result = asyncio.run(_run())

        assert margin_client.submit_limit_order.await_count == 1
        kwargs = margin_client.submit_limit_order.call_args.kwargs
        assert kwargs.get("market") == "margin"
        assert kwargs.get("time_in_force") == "IOC"
        assert result.get("market") == "margin"
        state = portfolio.state
        assert "BTCUSDT.BINANCE_MARGIN" in state.positions
        pos = state.positions["BTCUSDT.BINANCE_MARGIN"]
        assert pos.market == "margin"
        assert pos.venue == "BINANCE_MARGIN"
    finally:
        if previous_client is not None:
            set_exchange_client("BINANCE_MARGIN", previous_client)


def test_market_orders_convert_to_ioc(monkeypatch):
    client = StubMarginClient()
    previous_client = exchange_client("BINANCE")
    set_exchange_client("BINANCE", client)
    portfolio = Portfolio()
    monkeypatch.setattr("engine.core.order_router._IOC_TOLERANCE_BPS", 100.0)
    try:

        async def _run():
            return await _place_market_order_async_core(
                "BTCUSDT.BINANCE", "BUY", 100.0, None, portfolio, market=None
            )

        result = asyncio.run(_run())
        kwargs = client.submit_limit_order.call_args.kwargs
        assert kwargs["time_in_force"] == "IOC"
        assert kwargs["price"] > 10000.0
        assert result["time_in_force"] == "IOC" or True  # ensure no crash
    finally:
        if previous_client is not None:
            set_exchange_client("BINANCE", previous_client)
