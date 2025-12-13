import sys
from unittest.mock import MagicMock

# Mock heavy data science libraries missing on host
sys.modules["numpy"] = MagicMock()
sys.modules["pandas"] = MagicMock()
sys.modules["sklearn"] = MagicMock()
sys.modules["sklearn.cluster"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["httpx"] = MagicMock()
# Mock pkg
pkg = MagicMock()
sys.modules["engine.services"] = pkg
sys.modules["engine.services.param_client"] = MagicMock()

try:
    from engine.strategies.stat_arb.clustering import AssetClustering
    print("SUCCESS: Clustering module imported.")
    
    from engine.strategies.stat_arb.cointegration import RecursiveLeastSquares, CointegrationModel
    print("SUCCESS: Cointegration module imported.")
    
    # Test instantiation (will use mocks)
    ac = AssetClustering()
    print(f"SUCCESS: AssetClustering instantiated with lookback={ac.lookback}")
    
    rls = RecursiveLeastSquares()
    print(f"SUCCESS: RLS instantiated with forget={rls.forget}")
    
    cm = CointegrationModel("BTC", "ETH")
    print(f"SUCCESS: CointegrationModel instantiated for {cm.target}/{cm.hedge}")

except ImportError as e:
    print(f"FAILURE: ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"FAILURE: Exception: {e}")
    sys.exit(1)
