import sys
from unittest.mock import MagicMock

# Mock full dependency tree to allow import on minimal env
sys.modules["httpx"] = MagicMock()
sys.modules["engine.services"] = MagicMock()
sys.modules["engine.services.param_client"] = MagicMock()

# Also mock engine.models if needed, though policy_hmm might try to import it? 
# No, policy_hmm only imports from .calibration and VolatilityManager.

try:
    from engine.strategies import policy_hmm
    print("SUCCESS: policy_hmm imported cleanly.")
    
    vm = policy_hmm.VolatilityManager(target_vol_ann=0.40)
    print(f"SUCCESS: VolatilityManager instantiated from policy_hmm namespace. Target: {vm.target_vol}")
    
    # Test a dummy ingest to see if it crashes
    policy_hmm.ingest_tick("BTCUSDT", 50000.0)
    policy_hmm.ingest_tick("BTCUSDT", 50100.0)
    print("SUCCESS: ingest_tick ran without error.")
    
except ImportError as e:
    print(f"FAILURE: ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"FAILURE: Exception: {e}")
    sys.exit(1)
