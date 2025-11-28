import asyncio
import logging
import time
from unittest.mock import MagicMock, patch

try:
    from engine.risk import RiskRails
    from engine.config import RiskConfig, QUOTE_CCY
    from engine.core.portfolio import Portfolio
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_hardening")

def test_circuit_breaker():
    print("--- Testing Circuit Breaker ---")
    cfg = RiskConfig(trading_enabled=True)
    rails = RiskRails(cfg)
    
    # 1. Normal State
    allowed, _ = rails.check_order(symbol="BTCUSDT", side="BUY", quote=100.0, quantity=0.001)
    assert allowed, "Order should be allowed in normal state"
    
    # 2. Trip Breaker
    rails.set_circuit_breaker(True, "Test Reason")
    allowed, reason = rails.check_order(symbol="BTCUSDT", side="BUY", quote=100.0, quantity=0.001)
    assert not allowed, "Order should be blocked when breaker is active"
    assert reason["error"] == "CIRCUIT_BREAKER", f"Wrong error code: {reason}"
    print("✅ Circuit Breaker Verified")

def test_dynamic_quote_currency():
    print(f"--- Testing Dynamic Quote Currency ({QUOTE_CCY}) ---")
    portfolio = Portfolio()
    
    # Sync wallet with configured quote currency
    balances = {QUOTE_CCY: 5000.0, "BTC": 1.0}
    portfolio.sync_wallet(balances)
    
    assert portfolio.state.cash == 5000.0, f"Cash mismatch: {portfolio.state.cash}"
    print("✅ Dynamic Quote Currency Verified")

if __name__ == "__main__":
    test_circuit_breaker()
    test_dynamic_quote_currency()
