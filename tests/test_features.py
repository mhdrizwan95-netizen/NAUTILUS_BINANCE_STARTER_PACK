# tests/test_features.py
import numpy as np
from strategies.hmm_policy.features import FeatureState, compute_features
from strategies.hmm_policy.telemetry import Telemetry

def test_features_basic():
    st = FeatureState()
    # Mock book
    book = type("Book", (), {"best_bid_price": 50000.0, "best_ask_price": 50001.0,
                              "best_bid_size": 1.0, "best_ask_size": 0.5, "ts_ns": 1000})()
    feats = compute_features(None, book, [], st)
    assert isinstance(feats, np.ndarray)
    assert feats.dtype == np.float32
    assert feats.shape == (9,)
    assert not np.isnan(feats).any(), "No NaNs allowed"

def test_features_with_trades():
    st = FeatureState()
    book = type("Book", (), {"best_bid_price": 50000.0, "best_ask_price": 50001.0,
                              "best_bid_size": 1.0, "best_ask_size": 0.5, "ts_ns": 1000})()
    trades = [type("Trade", (), {"aggressor_side": "BUYER", "size": 0.1, "price": 50000.5})()]
    feats = compute_features(None, book, trades, st)
    assert feats.shape == (9,)
    assert not np.isnan(feats).any()

def test_performance():
    telemetry = Telemetry()
    st = FeatureState()
    # Generate synthetic data
    for i in range(100):
        book = type("Book", (), {"best_bid_price": 50000.0 + i*0.01, "best_ask_price": 50001.0 + i*0.01,
                                  "best_bid_size": 1.0, "best_ask_size": 0.5, "ts_ns": i*1000})()
        feats = telemetry.time_call(compute_features, None, book, [], st)
        assert feats.shape == (9,)

    avg_us = telemetry.avg_timing_us()
    print(f"Avg feature computation time: {avg_us:.1f} µs/tick")
    # TODO: Optimize to < 200 µs for production
    assert avg_us < 1000, f"Avg {avg_us} µs > 1000 µs limit"
