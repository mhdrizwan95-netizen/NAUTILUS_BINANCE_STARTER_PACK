import asyncio
import unittest
import sys
from unittest.mock import MagicMock, AsyncMock

# Mock dependencies to avoid needing installed packages (like httpx)
mock_router_module = MagicMock()
mock_router_module.OrderRouterExt = MagicMock
sys.modules["engine.core.order_router"] = mock_router_module

from engine.execution.smart_execute import SmartAlgorithm

class MockRouter:
    def __init__(self):
        self.exchange_client = MagicMock(return_value=MockClient())
        self.limit_quantity = AsyncMock()
        self.place_market_order_async = AsyncMock()
        self.get_last_price = AsyncMock(return_value=100.0)

class MockClient:
    def __init__(self):
        self.book_ticker = MagicMock(return_value={"bidPrice": "100.0", "askPrice": "100.1"})
        self.cancel_order = AsyncMock()

class TestSmartExecutor(unittest.IsolatedAsyncioTestCase):
    async def test_limit_chase_immediate_fill(self):
        router = MockRouter()
        # Mock immediate fill
        router.limit_quantity.return_value = {"orderId": "1", "filled_qty_base": "1.0", "avg_fill_price": "100.0"}
        
        smart = SmartAlgorithm(router)
        res = await smart.limit_chase("BTCUSDT", "BUY", 1.0)
        
        self.assertEqual(res["filled_qty_base"], "1.0")
        router.limit_quantity.assert_called_once()
        # Verify price was BBO bid
        args = router.limit_quantity.call_args
        self.assertEqual(args.kwargs["price"], 100.0)

    async def test_limit_chase_drift_and_fill(self):
        router = MockRouter()
        client = router.exchange_client()
        
        # Sequence of BBOs: 
        # 1. 100.0 (Initial)
        # 2. 100.5 (Drift up - Chase)
        # 3. 100.5 (Fill)
        
        # We need to mock get_bbo behavior or the client.book_ticker
        # SmartExec gets client from router.exchange_client("BINANCE")
        
        # Iteration 1 starts: BBO 100.0. limit_quantity called.
        # Loop sleep.
        # Iteration 2 check: BBO 100.5. Diff > 0. Cancel 1, Limit 2 @ 100.5.
        
        call_count = 0
        def side_effect_ticker(symbol):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"bidPrice": "100.0", "askPrice": "100.1"}
            else:
                 return {"bidPrice": "100.5", "askPrice": "100.6"}

        client.book_ticker.side_effect = side_effect_ticker
        
        # Mock limit_quantity to NOT fill first time, FILL second time
        async def side_effect_limit(**kwargs):
            if kwargs["price"] == 100.0:
                return {"orderId": "1", "filled_qty_base": "0.0"}
            else:
                return {"orderId": "2", "filled_qty_base": "1.0", "avg_fill_price": "100.5"}
        
        router.limit_quantity.side_effect = side_effect_limit
        
        smart = SmartAlgorithm(router)
        # Make interval minimal for test speed
        res = await smart.limit_chase("BTCUSDT", "BUY", 1.0, chase_interval=0.01)
        
        self.assertEqual(res["filled_qty_base"], "1.0")
        self.assertEqual(res["avg_fill_price"], "100.5")
        
        # Verify Cancel was called for orderId 1
        client.cancel_order.assert_called_with(symbol="BTCUSDT", orderId="1")
        
        # Verify number of limit placements
        self.assertEqual(router.limit_quantity.call_count, 2)

    async def test_twap_Basic(self):
        router = MockRouter()
        smart = SmartAlgorithm(router)
        smart.limit_chase = AsyncMock(return_value={"filled_qty_base": "0.25", "avg_fill_price": "100.0"})
        
        res = await smart.twap("BTCUSDT", "BUY", 1.0, duration=0.1, slices=4, algo_inner="chase")
        
        self.assertEqual(res["filled_qty_base"], 1.0)
        self.assertEqual(len(res["fills"]), 4)
        self.assertEqual(smart.limit_chase.call_count, 4)

if __name__ == '__main__':
    unittest.main()
