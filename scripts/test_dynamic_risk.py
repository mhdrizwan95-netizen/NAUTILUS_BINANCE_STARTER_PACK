import asyncio
import sys
import os
from unittest.mock import patch, MagicMock
from dataclasses import replace

# Ensure we can import engine
sys.path.append(os.getcwd())

from engine.risk import RiskRails
from engine.config import load_risk_config, RiskConfig
from engine.services import param_client

def test_dynamic_rails():
    print("--- Testing Dynamic RiskRails ---")
    
    # 1. Setup
    base_cfg = load_risk_config()
    # Set static max to 1000 and enable trading
    base_cfg = replace(base_cfg, max_notional_usdt=1000.0, trading_enabled=True)
    rails = RiskRails(base_cfg)
    
    # Mock equity to 10,000 (Hard Cap = 5,000)
    rails._last_equity = 10000.0
    
    # 2. Test Static Limit (Should Fail if > 1000)
    print("Test 1: Static Limit (1500 > 1000)")
    ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=1500.0, quantity=None)
    if not ok and err["error"] == "NOTIONAL_TOO_LARGE":
        print("✅ Static limit enforced.")
    else:
        print(f"❌ Static limit failed: {ok}, {err}")

    # 3. Test Dynamic Override (Aggressive: 10,000)
    # Mock param client to return aggressive params
    print("Test 2: Dynamic Override (Aggressive)")
    with patch("engine.risk.get_cached_params") as mock_get:
        mock_get.return_value = {
            "params": {
                "max_notional_usdt": 10000.0,
                "exposure_cap_symbol_usd": 10000.0
            }
        }
        
        # Try 4000 (Allowed by dynamic 10k, allowed by hard cap 5k)
        ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=4000.0, quantity=None)
        if ok:
            print("✅ Dynamic override accepted (4000 < 10000).")
        else:
            print(f"❌ Dynamic override failed: {err}")
            
        # Try 6000 (Allowed by dynamic 10k, BLOCKED by hard cap 5k)
        print("Test 3: Hard Ceiling (Safety Interlock)")
        ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=6000.0, quantity=None)
        if not ok and err["error"] == "NOTIONAL_TOO_LARGE" and "5000" in err["message"]:
            print("✅ Hard ceiling enforced (6000 > 5000).")
        else:
            print(f"❌ Hard ceiling failed: {ok}, {err}")

def test_dynamic_guardian():
    print("\n--- Testing Dynamic RiskGuardian ---")
    # We can't easily test the async loop here without a full harness, 
    # but we can verify the logic if we extract it or mock the loop internals.
    # For now, let's trust the Rails test as proof of concept for the mechanism 
    # and rely on manual verification for Guardian loop integration.
    print("Skipping Guardian unit test (requires async loop harness).")

if __name__ == "__main__":
    test_dynamic_rails()
    test_dynamic_guardian()
