import sys
import os
import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

# Ensure we can import engine/ops
sys.path.append(os.getcwd())

from ops.allocator import WealthManager, StrategyPerformance, ALLOCATIONS_PATH
from ops.telemetry_store import Metrics
from engine.risk import RiskRails
from engine.config import load_risk_config

def test_wealth_manager():
    print("--- Testing Wealth Manager ---")
    
    # 1. Setup Strategies
    # Strat A: Winner (High PnL, High Win Rate)
    strat_a = StrategyPerformance(
        strategy_id="winner_strat",
        metrics=Metrics(
            pnl_realized=1000.0,
            win_rate=0.8,
            max_drawdown=0.05,
            total_loss_pct=0.0
        )
    )
    
    # Strat B: Loser (Negative PnL, Low Win Rate)
    strat_b = StrategyPerformance(
        strategy_id="loser_strat",
        metrics=Metrics(
            pnl_realized=-500.0,
            win_rate=0.3,
            max_drawdown=0.10,
            total_loss_pct=0.05
        )
    )
    
    # Strat C: Bankrupt (Total Loss > 20%)
    strat_c = StrategyPerformance(
        strategy_id="bankrupt_strat",
        metrics=Metrics(
            pnl_realized=-2500.0,
            win_rate=0.1,
            max_drawdown=0.30,
            total_loss_pct=0.25
        )
    )
    
    wm = WealthManager(total_capital=10000.0)
    
    # 2. Run Allocation
    print("Running Allocation Cycle...")
    wm.allocate([strat_a, strat_b, strat_c])
    
    # 3. Verify Allocations
    allocs = wm.allocations
    print(f"Allocations: {json.dumps(allocs, indent=2)}")
    
    # Winner should have > Loser
    if allocs["winner_strat"] > allocs["loser_strat"]:
        print("✅ Winner rewarded > Loser.")
    else:
        print("❌ Winner not rewarded.")
        
    # Bankrupt should be 0
    if allocs["bankrupt_strat"] == 0.0:
        print("✅ Bankrupt strategy killed (Alloc=0).")
    else:
        print(f"❌ Bankrupt strategy survived: {allocs['bankrupt_strat']}")

def test_risk_enforcement():
    print("\n--- Testing Risk Enforcement ---")
    
    # 1. Setup RiskRails
    base_cfg = load_risk_config()
    base_cfg = replace(base_cfg, max_notional_usdt=5000.0, trading_enabled=True)
    rails = RiskRails(base_cfg)
    
    # 2. Mock Allocations File (Winner=2000, Bankrupt=0)
    mock_allocs = {
        "allocations": {
            "winner_strat": 2000.0,
            "bankrupt_strat": 0.0
        }
    }
    ALLOCATIONS_PATH.write_text(json.dumps(mock_allocs))
    
    # 3. Test Winner (Should accept up to 2000)
    print("Test 1: Winner Strat (Limit 2000)")
    # 1500 OK
    ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=1500.0, quantity=None, strategy_id="winner_strat")
    if ok:
        print("✅ Winner order accepted (1500 < 2000).")
    else:
        print(f"❌ Winner order rejected: {err}")
        
    # 2500 REJECT
    ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=2500.0, quantity=None, strategy_id="winner_strat")
    if not ok and err["error"] == "NOTIONAL_TOO_LARGE":
        print("✅ Winner order capped (2500 > 2000).")
    else:
        print(f"❌ Winner order check failed: {ok}, {err}")
        
    # 4. Test Bankrupt (Should REJECT ALL)
    print("Test 2: Bankrupt Strat (Limit 0)")
    ok, err = rails.check_order(symbol="BTCUSDT", side="BUY", quote=100.0, quantity=None, strategy_id="bankrupt_strat")
    if not ok and err["error"] == "STRATEGY_BANKRUPT":
        print("✅ Bankrupt order rejected immediately.")
    else:
        print(f"❌ Bankrupt order check failed: {ok}, {err}")

if __name__ == "__main__":
    test_wealth_manager()
    test_risk_enforcement()
