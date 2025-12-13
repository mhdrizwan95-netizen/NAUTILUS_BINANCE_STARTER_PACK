import unittest
import math
import sys
from unittest.mock import MagicMock

# Mock dependencies to avoid import chains triggering missing packages
sys.modules["httpx"] = MagicMock()
mock_services = MagicMock()
sys.modules["engine.services"] = mock_services
sys.modules["engine.services.param_client"] = MagicMock()

from engine.strategies.vol_target import VolatilityManager

class TestVolatilityManager(unittest.TestCase):
    def test_update_logic(self):
        vm = VolatilityManager(target_vol_ann=0.40, window=5, decay=0.94)
        
        prices = [100.0, 101.0, 102.0, 101.5, 103.0]
        for p in prices:
            vm.update(p)
            
        self.assertEqual(vm.current_variance > 0, True)
        self.assertEqual(len(vm.prices), 5)
        
    def test_target_exposure(self):
        vm = VolatilityManager(target_vol_ann=0.40)
        
        # Feed volatile prices
        prices = [100.0]
        import random
        random.seed(42)
        for _ in range(30):
            # 2% daily moves
            change = random.uniform(0.98, 1.02)
            prices.append(prices[-1] * change)
            
        for p in prices:
            vm.update(p)
            
        vol = vm.get_annualized_vol()
        print(f"Computed Vol: {vol:.4f}")
        
        equity = 10000.0
        exposure = vm.get_target_exposure(equity, cap_leverage=2.0)
        
        # Exposure should be inversely prop to vol.
        # If vol is high (>40%), exposure < equity.
        # If vol is low (<40%), exposure > equity (up to cap).
        
        if vol > 0.40:
            self.assertTrue(exposure < equity)
        else:
            self.assertTrue(exposure >= equity)

if __name__ == '__main__':
    unittest.main()
