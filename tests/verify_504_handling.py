import logging

# Mock the settings and other dependencies
import os
import unittest
from unittest.mock import AsyncMock, MagicMock

import httpx

os.environ["BINANCE_API_KEY"] = "test_key"
os.environ["BINANCE_API_SECRET"] = "test_secret"
os.environ["VENUE"] = "BINANCE"

from engine.core.binance import BinanceREST
from engine.core.order_router import _place_market_order_async_core
from engine.core.portfolio import Portfolio

# Configure logging
logging.basicConfig(level=logging.INFO)


class Test504Handling(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.portfolio = MagicMock(spec=Portfolio)
        self.portfolio.state = MagicMock()
        self.portfolio.state.positions = {}

        # Mock the Binance client
        self.mock_client = MagicMock(spec=BinanceREST)
        self.mock_client.submit_limit_order = AsyncMock()
        self.mock_client.submit_market_order = AsyncMock()  # Should not be called
        self.mock_client.order_status = AsyncMock()
        self.mock_client.get_last_price = MagicMock(
            return_value=100.0
        )  # Mock price for _resolve_last_price
        self.mock_client.exchange_filter = AsyncMock(return_value=None)  # Mock filter

        # Inject the mock client into the global _CLIENTS dictionary in order_router
        from engine.core import order_router

        order_router._CLIENTS["BINANCE"] = self.mock_client

    async def test_limit_ioc_conversion_and_504_orphan_found(self):
        """Test that Market orders are converted to Limit IOC and 504 orphan check works."""
        print("\n--- Testing Limit IOC Conversion & 504 Orphan Found ---")

        # Setup the mock to raise 504 on the first call
        error_504 = httpx.HTTPStatusError(
            message="Gateway Timeout", request=MagicMock(), response=MagicMock(status_code=504)
        )
        self.mock_client.submit_limit_order.side_effect = error_504

        # Setup the mock to return the order status when checked
        expected_order = {
            "orderId": 12345,
            "status": "FILLED",
            "executedQty": "1.0",
            "avg_fill_price": "100.0",
        }
        self.mock_client.order_status.return_value = expected_order

        # Call the function
        result = await _place_market_order_async_core(
            symbol="BTCUSDT.BINANCE", side="BUY", quote=None, quantity=1.0, portfolio=self.portfolio
        )

        # Verify result
        self.assertEqual(result, expected_order)

        # Verify Limit IOC conversion
        self.mock_client.submit_limit_order.assert_called_once()
        call_kwargs = self.mock_client.submit_limit_order.call_args.kwargs
        self.assertEqual(call_kwargs["time_in_force"], "IOC")
        self.assertEqual(call_kwargs["symbol"], "BTCUSDT")
        self.assertEqual(call_kwargs["side"], "BUY")
        # Price should be slightly higher than 100.0 due to tolerance (BUY)
        self.assertGreater(float(call_kwargs["price"]), 100.0)

        # Verify 504 handling
        self.mock_client.order_status.assert_called_once()
        print("✅ Test Passed: Limit IOC used and Orphan order recovered.")

    async def test_limit_ioc_retry_success(self):
        """Test that Limit IOC retry works after 504 and orphan not found."""
        print("\n--- Testing Limit IOC Retry Success ---")

        # Setup the mock to raise 504 on the first call, then succeed on the second
        error_504 = httpx.HTTPStatusError(
            message="Gateway Timeout", request=MagicMock(), response=MagicMock(status_code=504)
        )
        success_order = {
            "orderId": 67890,
            "status": "FILLED",
            "executedQty": "1.0",
            "avg_fill_price": "100.0",
        }
        self.mock_client.submit_limit_order.side_effect = [error_504, success_order]

        # Setup the mock to return empty/error when checking status (orphan not found)
        self.mock_client.order_status.side_effect = Exception("Order not found")

        # Call the function
        result = await _place_market_order_async_core(
            symbol="BTCUSDT.BINANCE", side="BUY", quote=None, quantity=1.0, portfolio=self.portfolio
        )

        # Verify
        self.assertEqual(result, success_order)
        self.assertEqual(self.mock_client.submit_limit_order.call_count, 2)

        # Verify args for both calls
        for call in self.mock_client.submit_limit_order.call_args_list:
            kwargs = call.kwargs
            self.assertEqual(kwargs["time_in_force"], "IOC")

        self.mock_client.order_status.assert_called_once()
        print("✅ Test Passed: Limit IOC retry succeeded.")


if __name__ == "__main__":
    unittest.main()
