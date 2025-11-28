import sys
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure we can import engine
sys.path.append(os.getcwd())

from engine.core.order_router import OrderRouter
from engine.core.portfolio import Portfolio

async def test_sniper_adaptive_execution():
    print("--- Testing Sniper (Adaptive Execution) ---")
    
    # 1. Setup Mocks
    mock_client = AsyncMock()
    mock_client.submit_limit_order = AsyncMock(return_value={
        "orderId": "123",
        "executedQty": "1.0",
        "avg_fill_price": "100.0",
        "status": "FILLED"
    })
    mock_client.book_ticker = AsyncMock(return_value={
        "bidPrice": "99.9",
        "askPrice": "100.1"
    })
    
    # Mock Portfolio
    mock_portfolio = MagicMock(spec=Portfolio)
    mock_portfolio.state = MagicMock()
    
    # Initialize Router
    router = OrderRouter(mock_client, mock_portfolio, venue="BINANCE")
    
    # 2. Test CHOP Regime (Should use MAKER / GTX)
    print("\nTest 1: CHOP Regime -> Maker (GTX)")
    with patch("engine.strategies.policy_hmm.get_regime", return_value={"regime": "CHOP"}):
        # We need to mock _quote_to_quantity to avoid symbol spec issues
        router._quote_to_quantity = AsyncMock(return_value=1.0)
        router.get_last_price = AsyncMock(return_value=100.0)
        
        await router.market_quote(symbol="BTCUSDT", side="BUY", quote=100.0)
        
        # Verify submit_limit_order called with GTX
        calls = mock_client.submit_limit_order.call_args_list
        if calls:
            kwargs = calls[-1].kwargs
            print(f"Call args: {kwargs}")
            if kwargs.get("time_in_force") == "GTX":
                print("✅ Correctly used Post-Only (GTX) for CHOP regime.")
            else:
                print(f"❌ Failed to use GTX. Got: {kwargs.get('time_in_force')}")
        else:
            print("❌ submit_limit_order not called.")

    # 3. Test BULL Regime (Should use TAKER / IOC)
    print("\nTest 2: BULL Regime -> Taker (IOC)")
    mock_client.submit_limit_order.reset_mock()
    with patch("engine.strategies.policy_hmm.get_regime", return_value={"regime": "BULL"}):
        await router.market_quote(symbol="BTCUSDT", side="BUY", quote=100.0)
        
        calls = mock_client.submit_limit_order.call_args_list
        if calls:
            kwargs = calls[-1].kwargs
            print(f"Call args: {kwargs}")
            if kwargs.get("time_in_force") == "IOC":
                print("✅ Correctly used Taker (IOC) for BULL regime.")
            else:
                print(f"❌ Failed to use IOC. Got: {kwargs.get('time_in_force')}")
        else:
            print("❌ submit_limit_order not called.")

if __name__ == "__main__":
    asyncio.run(test_sniper_adaptive_execution())
