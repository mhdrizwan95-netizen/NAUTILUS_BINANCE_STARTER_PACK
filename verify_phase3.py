import asyncio
from unittest.mock import AsyncMock, MagicMock

from engine.core.order_router import OrderRouterExt
from engine.risk import RiskConfig, RiskRails
from engine.strategies import policy_hmm

# Mock config
cfg = RiskConfig(
    trading_enabled=True,
    max_orders_per_min=100,
    max_notional_usdt=1000.0,
    min_notional_usdt=10.0,
    trade_symbols=["BTCUSDT"],
    symbol_lock_ttl_sec=60.0,
    exposure_cap_symbol_usd=1000.0,
    exposure_cap_total_usd=1000.0,
    exposure_cap_venue_usd=1000.0,
    margin_enabled=False,
    options_enabled=False,
    dust_threshold_usd=1.0,
    venue_error_breaker_pct=0.5,
    venue_error_window_sec=60,
    equity_floor_usd=100.0,
    equity_drawdown_limit_pct=0.1,
    equity_cooldown_sec=300,
    margin_min_level=1.1,
    margin_max_liability_usd=10000.0,
    margin_max_leverage=5.0,
)


def test_risk_lock():
    print("Testing RiskRails Central Lock...")
    rails = RiskRails(cfg)

    # Strategy A acquires lock
    ok, err = rails.check_order(
        symbol="BTCUSDT", side="BUY", quote=100.0, quantity=None, strategy_id="StrategyA"
    )
    assert ok, f"StrategyA failed to acquire lock: {err}"
    print("StrategyA acquired lock.")

    # Strategy B tries to acquire lock (should fail)
    ok, err = rails.check_order(
        symbol="BTCUSDT", side="BUY", quote=100.0, quantity=None, strategy_id="StrategyB"
    )
    assert not ok, "StrategyB should have been blocked"
    assert err["error"] == "SYMBOL_LOCKED", f"Unexpected error: {err}"
    print("StrategyB correctly blocked.")

    # Strategy A extends lock (should succeed)
    ok, err = rails.check_order(
        symbol="BTCUSDT", side="BUY", quote=100.0, quantity=None, strategy_id="StrategyA"
    )
    assert ok, f"StrategyA failed to extend lock: {err}"
    print("StrategyA extended lock.")

    print("RiskRails Central Lock Test Passed!")


async def test_order_router():
    print("\nTesting OrderRouter Limit IOC...")

    # Mock Client
    client = MagicMock()
    client.get_last_price = AsyncMock(return_value=100.0)
    client.submit_limit_order = AsyncMock(
        return_value={"status": "FILLED", "executedQty": 1.0, "avg_fill_price": 100.0}
    )
    client.submit_market_quote = AsyncMock(return_value={"status": "FILLED"})  # Fallback

    # Mock Portfolio
    portfolio = MagicMock()

    router = OrderRouterExt(client, portfolio, venue="BINANCE")

    # Test market_quote calls submit_limit_order with IOC
    await router.market_quote("BTCUSDT", "BUY", quote=100.0)

    # Verify submit_limit_order was called
    client.submit_limit_order.assert_called_once()
    call_args = client.submit_limit_order.call_args[1]
    assert call_args["time_in_force"] == "IOC", "Order was not IOC"
    assert call_args["price"] > 100.0, "Limit price should be higher than mark for BUY"
    print("OrderRouter correctly submitted Limit IOC order.")

    print("OrderRouter Limit IOC Test Passed!")


def test_hmm_gating():
    print("\nTesting HMM Gating Logic (Mock)...")
    # We can't easily test TrendStrategy without full setup, but we can verify policy_hmm.get_regime exists
    assert hasattr(policy_hmm, "get_regime"), "policy_hmm.get_regime missing"
    print("policy_hmm.get_regime exists.")


if __name__ == "__main__":
    test_risk_lock()
    test_hmm_gating()
    asyncio.run(test_order_router())
