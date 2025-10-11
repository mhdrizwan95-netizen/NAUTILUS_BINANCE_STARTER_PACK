import os, importlib, json
from fastapi.testclient import TestClient

def test_hmm_loop_respects_cooldown(monkeypatch):
    os.environ["STRATEGY_ENABLED"] = "true"
    os.environ["STRATEGY_DRY_RUN"] = "true"
    os.environ["HMM_ENABLED"] = "true"
    os.environ["TRADE_SYMBOLS"] = "BTCUSDT"
    os.environ["COOLDOWN_SEC"] = "9999"  # very long cooldown to test
    # Stub model
    from engine.strategies import policy_hmm as hmm
    def fake_model():
        class M:
            def predict_proba(self, X): return [[0.7, 0.2, 0.1]]
        return M()
    hmm._model = fake_model()
    from engine import strategy
    importlib.reload(strategy)
    # Reset HMM state for test
    hmm._prices.clear()
    hmm._vols.clear()
    hmm._last_signal_ts.clear()
    # Feed one tick that should trigger a signal
    hmm.ingest_tick("BTCUSDT", 50000, 1)
    # Future ticks should be ignored due to cooldown
    hmm.ingest_tick("BTCUSDT", 50001, 1)
    hmm.ingest_tick("BTCUSDT", 50002, 1)
    # Only first decide() call should return a decision
    assert hmm.decide("BTCUSDT") is not None  # first call succeeds
    assert hmm.decide("BTCUSDT") is None      # subsequent calls blocked by cooldown
