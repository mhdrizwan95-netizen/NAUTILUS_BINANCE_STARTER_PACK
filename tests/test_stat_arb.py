import unittest
import numpy as np
import pandas as pd
from engine.strategies.stat_arb.cointegration import RecursiveLeastSquares
from engine.strategies.stat_arb.clustering import AssetClustering

class TestStatArb(unittest.TestCase):
    
    def test_rls_convergence(self):
        """Test if RLS converges to the true beta."""
        real_beta = 2.5
        real_alpha = 10.0
        
        # Generate data y = 2.5x + 10 + noise
        rls = RecursiveLeastSquares(n_features=2, forget=0.999)
        
        np.random.seed(42)
        X = np.linspace(0, 100, 500)
        Y = (real_beta * X) + real_alpha + np.random.normal(0, 0.5, 500)
        
        for x, y in zip(X, Y):
            feats = np.array([x, 1.0])
            rls.update(feats, y)
            
        print(f"RLS Beta: {rls.slope:.4f} (True: {real_beta})")
        print(f"RLS Alpha: {rls.intercept:.4f} (True: {real_alpha})")
        
        self.assertAlmostEqual(rls.slope, real_beta, places=1)
        self.assertAlmostEqual(rls.intercept, real_alpha, places=1)

    def test_clustering_dbscan(self):
        """Test clustering on synthetic correlated data."""
        # Create 3 series: A, B (correlated), C (uncorrelated)
        np.random.seed(42)
        idx = pd.date_range("2023-01-01", periods=100, freq="min")
        
        sA = np.random.normal(0, 0.01, 100).cumsum() + 100
        sB = sA * 1.01 + np.random.normal(0, 0.02, 100) # Highly correllated
        sC = np.random.normal(0, 0.01, 100).cumsum() + 100 # Random walk
        
        df = pd.DataFrame({
            "A": sA, 
            "B": sB, 
            "C": sC
        }, index=idx)
        
        clustering = AssetClustering(lookback=100, eps=0.5, min_samples=2)
        clusters = clustering.cluster_from_prices(df)
        
        print("Clusters found:", clusters)
        
        # Expect A and B to be in the same cluster
        self.assertTrue(len(clusters) >= 1)
        # Check if A and B are together in one of the values
        found_pair = False
        for c_id, members in clusters.items():
            if "A" in members and "B" in members:
                found_pair = True
                
        self.assertTrue(found_pair, "A and B should be clustered together")

if __name__ == '__main__':
    unittest.main()
