import logging
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
from typing import List, Dict

logger = logging.getLogger(__name__)

class AssetClustering:
    """
    Cluster assets based on correlation of historical returns using DBSCAN.
    """
    def __init__(self, lookback: int = 1440, min_samples: int = 2, eps: float = 0.5):
        """
        :param lookback: Number of minutes/periods to use for correlation.
        :param min_samples: DBSCAN min_samples (min cluster size).
        :param eps: DBSCAN epsilon (max distance for neighborhood).
        """
        self.lookback = lookback
        self.min_samples = min_samples
        self.eps = eps
        
        # Buffer to store returns: {symbol: [r1, r2, ...]}
        # We need a proper structure to align timestamps. 
        # For simplicity in this iteration, we assume aligned ingestion or we build a DF.
        self._returns_buffer: Dict[str, List[float]] = {}
        self._max_len = lookback * 2

    def update(self, prices: Dict[str, float]):
        """
        Update return buffers with a dictionary of {symbol: current_price}.
        Should be called once per minute/tick alignment.
        """
        # Note: This is a simplifed scalar update. 
        # In production, we'd manage a DataFrame directly or use a sliding window cache.
        pass

    def cluster_from_prices(self, price_df: pd.DataFrame) -> Dict[int, List[str]]:
        """
        Perform clustering on a DataFrame of prices (Index=Time, Col=Symbol).
        Asset must have full history in the window to be included (drop NaN).
        """
        if price_df.empty:
            return {}

        # 1. Calculate Log Returns
        returns = np.log(price_df / price_df.shift(1)).dropna()
        
        if returns.shape[0] < self.lookback:
            logger.warning(f"[Clustering] Not enough data: {returns.shape[0]} < {self.lookback}")
            return {}

        # 2. Correlation Matrix
        # Transpose so rows are assets, cols are observations
        # corr() calculates col-vs-col correlation.
        corr_matrix = returns.corr()
        
        # 3. Distance Matrix
        # DBSCAN needs distance. 
        # Distance = sqrt(2 * (1 - Correlation))
        # Corr 1.0 -> Dist 0.0
        # Corr 0.0 -> Dist 1.41
        # Corr -1.0 -> Dist 2.0
        dist_matrix = np.sqrt(2 * (1 - corr_matrix))
        
        # Be robust to tiny floating point errors (sqrt of negative)
        dist_matrix = dist_matrix.fillna(2.0)
        
        # 4. DBSCAN
        # metric='precomputed' expects a distance matrix
        db = DBSCAN(eps=self.eps, min_samples=self.min_samples, metric='precomputed')
        labels = db.fit_predict(dist_matrix)
        
        # 5. Group Results
        clusters = {}
        assets = corr_matrix.columns.tolist()
        
        for idx, label in enumerate(labels):
            if label == -1:
                # Noise point, ignore
                continue
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(assets[idx])
            
        logger.info(f"[Clustering] Found {len(clusters)} clusters from {len(assets)} assets.")
        return clusters
