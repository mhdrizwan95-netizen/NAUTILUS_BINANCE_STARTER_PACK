import pytest
from unittest.mock import Mock, patch, AsyncMock
import asyncio

from engine.core.order_router import (
    OrderRouter,
    _place_market_order_async_core,
    _round_step,
    _round_step_up,
    exchange_client,
    set_exchange_client,
)
from engine.core.portfolio import Portfolio


class StubMarginClient:
    def __init__(self):
        self.submit_market_quote = AsyncMock(
            return_value={
                "symbol": "BTCUSDT",
                "executedQty": 0.01,
                "avg_fill_price": 10000.0,
                "filled_qty_base": 0.01,
            }
        )
        self.ticker_price = Mock(return_value=10000.0)
        self.exchange_filter = AsyncMock(return_value=None)


class TestOrderRouterKraken:
    """Test Kraken-specific order routing behavior."""

    @pytest.fixture
    def mock_kraken_client(self):
        """Mock Kraken client for IOC limit order submission."""
        client = Mock()
        client.submit_limit_order = AsyncMock()
        client.exchange_filter = AsyncMock(return_value=None)
        # Mock ticker_price for price resolution
        client.ticker_price = Mock(return_value=50000.0)
        return client

    @pytest.fixture
    def mock_portfolio(self):
        """Mock portfolio for order router."""
        return Mock(spec=Portfolio)

    @pytest.fixture(autouse=True)
    def setup_router(self, mock_kraken_client, mock_portfolio):
        """Setup order router with mocked Kraken client."""
        set_exchange_client("KRAKEN", mock_kraken_client)
        self.router = OrderRouter(mock_kraken_client, mock_portfolio, venue="KRAKEN")

    @patch("engine.core.order_router._resolve_last_price", return_value=50000.0)
    async def test_kraken_ioc_order_submission(
        self, mock_resolve_price, mock_kraken_client
    ):
        """Test Kraken orders use IOC time_in_force."""
        mock_kraken_client.submit_limit_order.return_value = {
            "executedQty": 0.1,
            "avg_fill_price": 50050.0,
            "filled_qty_base": 0.1,
            "fee_usd": 0.125,
        }

        result = await _place_market_order_async_core(
            symbol="BTC.KRAKEN", side="BUY", quote=10.0, quantity=None, portfolio=None
        )

        # Verify IOC was used
        mock_kraken_client.submit_limit_order.assert_called_once()
        call_args = mock_kraken_client.submit_limit_order.call_args
        assert call_args[1]["time_in_force"] == "IOC"

    @patch("engine.core.order_router._resolve_last_price", return_value=50000.0)
    async def test_kraken_slippage_calculation(
        self, mock_resolve_price, mock_kraken_client
    ):
        """Test Kraken limit price includes 0.2% slippage for BUY orders."""
        mock_kraken_client.submit_limit_order.return_value = {
            "executedQty": 0.1,
            "avg_fill_price": 50100.0,
            "filled_qty_base": 0.1,
            "fee_usd": 0.125,
        }

        await _place_market_order_async_core(
            symbol="BTC.KRAKEN", side="BUY", quote=10.0, quantity=None, portfolio=None
        )

        call_args = mock_kraken_client.submit_limit_order.call_args
        expected_limit_price = 50000.0 * (1 + 0.002)  # BUY: add slippage
        assert call_args[1]["price"] == pytest.approx(expected_limit_price)

    @patch("engine.core.order_router._resolve_last_price", return_value=50000.0)
    async def test_kraken_slippage_sell_order(
        self, mock_resolve_price, mock_kraken_client
    ):
        """Test Kraken limit price includes 0.2% slippage for SELL orders."""
        mock_kraken_client.submit_limit_order.return_value = {
            "executedQty": 0.1,
            "avg_fill_price": 49900.0,
            "filled_qty_base": 0.1,
            "fee_usd": 0.125,
        }

        await _place_market_order_async_core(
            symbol="BTC.KRAKEN", side="SELL", quote=10.0, quantity=None, portfolio=None
        )

        call_args = mock_kraken_client.submit_limit_order.call_args
        expected_limit_price = 50000.0 * (1 - 0.002)  # SELL: subtract slippage
        assert call_args[1]["price"] == pytest.approx(expected_limit_price)

    async def test_round_step_up_vs_round_step(self):
        """Test that _round_step_up rounds up vs _round_step which rounds to nearest."""
        step_size = 0.1

        # Test value that would round down with regular rounding
        value = 0.05

        regular_round = _round_step(value, step_size)
        round_up = _round_step_up(value, step_size)

        assert regular_round == 0.0  # 0.05 rounds to 0 with step 0.1
        assert round_up == 0.1  # _round_step_up rounds up to 0.1

    @patch("engine.core.order_router._resolve_last_price", return_value=50000.0)
    async def test_kraken_quantity_rounding_up(
        self, mock_resolve_price, mock_kraken_client
    ):
        """Test Kraken uses _round_step_up for quantity calculation."""
        mock_kraken_client.submit_limit_order.return_value = {
            "executedQty": 0.1,
            "avg_fill_price": 50050.0,
            "filled_qty_base": 0.1,
            "fee_usd": 0.125,
        }

        # Use quote that results in 0.05 quantity (will round up to 0.1 for Kraken)
        await _place_market_order_async_core(
            symbol="BTC.KRAKEN",
            side="BUY",
            quote=2500.0,  # 2500 / 50000 = 0.05
            quantity=None,
            portfolio=None,
        )

        call_args = mock_kraken_client.submit_limit_order.call_args
        assert call_args[1]["quantity"] == 0.1  # Rounded up from 0.05

    @patch("engine.core.order_router._resolve_last_price", return_value=50000.0)
    async def test_kraken_symbol_normalization(
        self, mock_resolve_price, mock_kraken_client
    ):
        """Test Kraken symbols are properly normalized for API calls."""
        mock_kraken_client.submit_limit_order.return_value = {
            "executedQty": 0.1,
            "avg_fill_price": 50050.0,
            "filled_qty_base": 0.1,
        }

        await _place_market_order_async_core(
            symbol="BTC.KRAKEN", side="BUY", quote=10.0, quantity=None, portfolio=None
        )

        call_args = mock_kraken_client.submit_limit_order.call_args
        assert call_args[1]["symbol"] == "BTC"  # Base symbol only

    async def test_binance_does_not_use_round_step_up(self):
        """Verify Binance does NOT use round_step_up (for comparison)."""
        # This tests the difference between venues
        step_size = 0.1
        value = 0.05

        # Kraken would round up: 0.05 -> 0.1
        kraken_qty = _round_step_up(value, step_size)
        assert kraken_qty == 0.1

        # Binance/other would use regular rounding: 0.05 -> 0.0
        other_qty = _round_step(value, step_size)
        assert other_qty == 0.0


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

        assert margin_client.submit_market_quote.await_count == 1
        kwargs = margin_client.submit_market_quote.call_args.kwargs
        assert kwargs.get("market") == "margin"
        assert result.get("market") == "margin"
        state = portfolio.state
        assert "BTCUSDT.BINANCE_MARGIN" in state.positions
        pos = state.positions["BTCUSDT.BINANCE_MARGIN"]
        assert pos.market == "margin"
        assert pos.venue == "BINANCE_MARGIN"
    finally:
        if previous_client is not None:
            set_exchange_client("BINANCE_MARGIN", previous_client)
