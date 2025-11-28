import asyncio
import sys
import os
from unittest.mock import patch, MagicMock

# Ensure we can import engine
sys.path.append(os.getcwd())

from dataclasses import replace
from httpx import AsyncClient, ASGITransport
from engine.app import app, RAILS

async def delayed_execution(*args, **kwargs):
    await asyncio.sleep(0.2)  # 200ms delay to force overlap
    return {
        "id": "test_order",
        "symbol": "BTCUSDT",
        "status": "FILLED",
        "avg_fill_price": 50000.0,
        "filled_qty_base": 0.001,
        "venue": "BINANCE"
    }

async def main():
    print("Starting Race Condition Test...")
    
    # Create enabled config
    new_cfg = replace(RAILS.cfg, trading_enabled=True)

    # Patch the router execution to be slow AND enable trading AND disable breaker logic
    with patch("engine.app.router.market_quantity", side_effect=delayed_execution) as mock_exec, \
         patch.object(RAILS, "cfg", new_cfg), \
         patch("engine.risk.RiskRails.refresh_snapshot_metrics") as mock_metrics:
        
        # Mock healthy metrics state
        mock_metrics.return_value = RAILS.SnapshotMetricsState(breaker_active=False)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            
            # Fire 10 concurrent orders
            tasks = []
            payload = {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.001,
                "venue": "BINANCE"
            }
            
            print("Firing 10 concurrent orders...")
            for i in range(10):
                tasks.append(client.post("/orders/market", json=payload))
            
            responses = await asyncio.gather(*tasks)
            
            success = 0
            race_fails = 0
            other_fails = 0
            
            for i, r in enumerate(responses):
                data = r.json()
                if r.status_code == 200 and data.get("status") == "submitted":
                    success += 1
                elif data.get("error") == "RACE_CONDITION_PENDING_ORDER":
                    race_fails += 1
                else:
                    other_fails += 1
                    print(f"Order {i} failed with unexpected error: {data}")

            print("-" * 30)
            print(f"Total Requests: {len(responses)}")
            print(f"Successes: {success}")
            print(f"Race Rejections: {race_fails}")
            print(f"Other Failures: {other_fails}")
            print("-" * 30)
            
            if success == 1 and race_fails == 9:
                print("✅ TEST PASSED: Exact concurrency control verified.")
            elif success > 1:
                print("❌ TEST FAILED: Multiple orders succeeded (Lock failed).")
            elif race_fails == 0:
                print("❌ TEST FAILED: No race conditions detected (Test might be too slow or lock not working).")
            else:
                print("⚠️ TEST RESULT INCONCLUSIVE (Check output).")

if __name__ == "__main__":
    asyncio.run(main())
