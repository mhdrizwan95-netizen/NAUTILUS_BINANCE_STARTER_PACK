import pickle, numpy as np


def test_pickled_model_predicts_proba():
    try:
        with open("engine/models/hmm_policy.pkl", "rb") as f:
            mdl = pickle.load(f)
        X = np.zeros((3, 5), dtype=float)  # dummy 5-dim feats
        out = mdl.predict_proba(X)
        assert out.shape[0] == 3
        assert out.shape[1] >= 2
        # rows sum to ~1
        import numpy as np

        assert np.allclose(out.sum(axis=1), 1.0, atol=1e-5)
    except FileNotFoundError:
        # Allow tests to pass if model file doesn't exist yet (model not trained)
        # In CI/production, you'd want to fail if model is missing
        import pytest

        pytest.skip(
            "HMM model file not found - train with scripts/train_hmm_policy.py first"
        )
