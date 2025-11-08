# tests/test_h2.py — M13: Hierarchical HMM smoke tests
from fastapi.testclient import TestClient

from ml_service.app import app

client = TestClient(app)


def test_h2_train_and_infer_smoke():
    # tiny synthetic data
    macro = [
        [0, 0, 0, 0, 0, 0],  # vol=0, trend=0
        [1, 1, 1, 1, 0.1, 1],  # vol=1, trend=1
        [0.5, 0.5, 0.5, 0.6, 0.0, 1],  # vol=0.5, trend=1
    ]
    micro_by = {
        0: [[1, 2, 3], [1, 2, 4]],  # macro 0 sequences
        1: [[5, 6, 7], [5, 6, 6]],  # macro 1 sequences
        2: [[0, 1, 0], [1, 1, 0]],  # macro 2 sequences
    }
    r = client.post(
        "/train_h2",
        json={
            "symbol": "BTCUSDT",
            "macro_sequences": macro,
            "micro_sequences_by_macro": micro_by,
            "n_macro": 3,
            "n_micro": 2,
        },
    )
    assert r.status_code == 200
    tag = r.json()["tag"]
    assert tag.startswith("h2-")

    ir = client.post(
        "/infer_h2",
        json={
            "symbol": "BTCUSDT",
            "macro_feats": [1, 1, 1, 1, 0.1, 1],
            "micro_feats": [5, 6, 7],
            "ts": 123,
            "tag": tag,
        },
    )
    assert ir.status_code == 200
    body = ir.json()
    assert "macro_state" in body and "micro_state" in body and "confidence" in body
    assert body["macro_state"] in [0, 1, 2]
    assert body["micro_state"] in [0, 1]
    assert 0.0 <= body["confidence"] <= 1.0


def test_h2_fallback_to_single():
    # Test fallback when H2 model not found
    ir = client.post(
        "/infer_h2",
        json={
            "symbol": "BTCUSDT",
            "macro_feats": [1, 1, 1, 1, 0.1, 1],
            "micro_feats": [5, 6, 7],
            "ts": 123,
            "tag": "nonexistent_h2_tag",
        },
    )
    assert ir.status_code == 200
    body = ir.json()
    # Should fallback to regular /infer response format
    assert "macro_state" in body and "micro_state" in body and "confidence" in body
