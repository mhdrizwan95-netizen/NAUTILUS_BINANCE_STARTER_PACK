# tests/test_features.py
import numpy as np
from strategies.hmm_policy.features import FeatureState, compute_features

def test_features_shape():
    st = FeatureState(None, None, None, None)
    feats = compute_features(None, type("B", (), {})(), [], st)
    assert isinstance(feats, np.ndarray)
    assert feats.dtype == np.float32
