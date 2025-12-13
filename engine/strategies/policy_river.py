
import os
import pickle
import logging
from typing import Any

import redis
try:
    from river import tree, compose, preprocessing, drift
except ImportError:
    # Fallback/Mock for environments where river isn't installed
    tree = None  # type: ignore
    compose = None  # type: ignore
    preprocessing = None  # type: ignore
    drift = None  # type: ignore

class RiverPolicy:
    """
    Online Learning Policy using River.
    Adapts to concept drift using Hoeffding Adaptive Tree + ADWIN.
    Persists state to Redis for crash recovery.
    """
    
    REDIS_KEY = "model:river:v1"

    def __init__(self):
        self.redis = None
        self.model = None
        self.drift_detector = None
        self.drift_count = 0
        # Track pending state per symbol for delayed feedback
        # { "BTCUSDT": {"feats": {...}, "price": 50000.0} }
        self.pending = {}
        
        # Connect to Redis
        host = os.getenv("REDIS_HOST")
        if host:
            try:
                self.redis = redis.Redis(
                    host=host,
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=0,
                    decode_responses=False
                )
                self.redis.ping()
            except Exception as e:
                logging.getLogger(__name__).warning(f"[River] Redis connection failed: {e}")
                self.redis = None
        
        # Load or Create Model
        self._load_model()
        
        # Initialize ADWIN Drift Detector
        if drift:
            self.drift_detector = drift.ADWIN(delta=0.002)
    
    def _create_pipeline(self):
        if not tree:
            return None
        return compose.Pipeline(
            preprocessing.StandardScaler(),
            tree.HoeffdingAdaptiveTreeClassifier(
                grace_period=100,
                split_criterion='gini',
                delta=1e-5,
                tau=0.05,
                seed=42
            )
        )

    def _load_model(self):
        loaded = False
        if self.redis:
            try:
                data = self.redis.get(self.REDIS_KEY)
                if data:
                    self.model = pickle.loads(data)
                    loaded = True
                    logging.getLogger(__name__).info("[River] Loaded model from Redis.")
            except Exception as e:
                logging.getLogger(__name__).warning(f"[River] Load failed: {e}")
        
        if not loaded:
            logging.getLogger(__name__).info("[River] Creating fresh DAG model.")
            self.model = self._create_pipeline()

    def save(self):
        if self.redis and self.model:
            try:
                data = pickle.dumps(self.model)
                self.redis.set(self.REDIS_KEY, data)
            except Exception as e:
                logging.getLogger(__name__).warning(f"[River] Save failed: {e}")

    def on_tick(self, symbol: str, features: dict, price: float) -> dict:
        """
        Main loop: Learn from previous tick -> Predict current tick.
        Monitors for concept drift using ADWIN.
        Returns: { "prediction": int, "proba": dict, "drift": bool }
        """
        if not self.model:
            return {}

        drift_detected = False
        
        # 1. Learn from past
        if symbol in self.pending:
            prev = self.pending[symbol]
            prev_price = prev["price"]
            prev_feats = prev["feats"]
            prev_pred = prev.get("pred", 0)
            
            # Label Generation: Did price go UP?
            if price > prev_price:
                label = 1
            elif price < prev_price:
                label = 0
            else:
                label = None  # Flat, skip learning
            
            if label is not None:
                try:
                    self.model.learn_one(prev_feats, label)
                    
                    # ADWIN Drift Detection
                    if self.drift_detector:
                        # Feed prediction error (1 if wrong, 0 if correct)
                        error = 1 if prev_pred != label else 0
                        self.drift_detector.update(error)
                        if self.drift_detector.drift_detected:
                            drift_detected = True
                            self.drift_count += 1
                            logging.getLogger(__name__).warning(
                                f"[River] DRIFT DETECTED for {symbol}! Count={self.drift_count}. Resetting model."
                            )
                            # Reset model to adapt to new regime
                            self.model = self._create_pipeline()
                            self.drift_detector = drift.ADWIN(delta=0.002)
                except Exception as e:
                    pass

        # 2. Predict current
        pred = 0
        proba = {}
        try:
            pred = self.model.predict_one(features)
            proba = self.model.predict_proba_one(features)
        except Exception:
            pass

        # 3. Store state for next tick (include prediction for ADWIN feedback)
        self.pending[symbol] = {
            "feats": features,
            "price": price,
            "pred": pred
        }
        
        return {
            "prediction": pred,
            "proba": proba,
            "drift": drift_detected
        }
