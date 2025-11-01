from fastapi.testclient import TestClient
from sklearn.preprocessing import StandardScaler
import numpy as np


class _DummyModel:
    def predict_proba(self, X):
        # two-state dummy; returns [p, 1-p] where p based on sign of last feature
        x = float(X[-1][0]) if len(X) else 0.0
        p = 0.8 if x >= 0 else 0.2
        return np.array([[p, 1 - p]])


def _app_with_dummy(monkeypatch):
    from services.ml_service.app import main as ml_main
    from services.ml_service.app import model_store

    def _load_current():
        scaler = StandardScaler()
        scaler.mean_ = np.array([0.0])
        scaler.scale_ = np.array([1.0])
        scaler.n_samples_seen_ = 1
        return _DummyModel(), scaler, {"version_id": "test-1", "n_states": 2}

    monkeypatch.setattr(model_store, "load_current", _load_current)
    # restart lifespan may start watchdog; skip and just return app
    return ml_main.app


def test_predict_contract(monkeypatch):
    app = _app_with_dummy(monkeypatch)
    client = TestClient(app)
    payload = {"logret": [0.0, 0.1, -0.05, 0.02]}
    r = client.post("/predict", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "regime_proba" in body and isinstance(body["regime_proba"], list)
    assert "model_meta" in body and body["model_meta"]["version_id"] == "test-1"
