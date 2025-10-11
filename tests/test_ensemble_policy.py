import pytest
from engine.strategies import ensemble_policy


def test_ensemble_disabled_returns_none():
    """Test that ensemble returns None when disabled."""
    ensemble_policy.S.ensemble_enabled = False
    result = ensemble_policy.combine("BTCUSDT", "BUY", 0.8, ("BUY", 10.0, {"probs": [0.9]}))
    assert result is None


def test_strong_consensus_both_buy():
    """Test strong consensus when both models agree on BUY."""
    ensemble_policy.S.ensemble_enabled = True
    ensemble_policy.S.ensemble_min_conf = 0.6
    ensemble_policy.S.ensemble_weights = {"hmm_v1": 0.5, "ma_v1": 0.5}

    result = ensemble_policy.combine("BTCUSDT", "BUY", 0.8, ("BUY", 10.0, {"probs": [0.9]}))
    assert result is not None
    side, quote, meta = result
    assert side == "BUY"
    assert quote == ensemble_policy.S.quote_usdt
    assert meta["exp"] == "ensemble_v1"
    assert meta["conf"] > ensemble_policy.S.ensemble_min_conf


def test_conflicting_signals_weak_consensus():
    """Test low confidence when models disagree."""
    ensemble_policy.S.ensemble_enabled = True
    ensemble_policy.S.ensemble_min_conf = 0.7  # High threshold

    # MA says BUY strongly, HMM says SELL weakly
    result = ensemble_policy.combine("BTCUSDT", "BUY", 0.9, ("SELL", 10.0, {"probs": [0.2]}))
    assert result is None  # Should be filtered out by min_conf


def test_weak_conf_signals_filtered():
    """Test that weak individual signals are filtered."""
    ensemble_policy.S.ensemble_enabled = True
    ensemble_policy.S.ensemble_min_conf = 0.8

    # All signals are weak
    result = ensemble_policy.combine("BTCUSDT", "BUY", 0.3, ("BUY", 10.0, {"probs": [0.4]}))
    assert result is None


def test_no_hmm_signal_ma_only():
    """Test MA-only signal when HMM doesn't trigger."""
    ensemble_policy.S.ensemble_enabled = True
    ensemble_policy.S.ensemble_min_conf = 0.6
    ensemble_policy.S.ensemble_weights = {"hmm_v1": 0.3, "ma_v1": 0.7}  # Favor MA

    result = ensemble_policy.combine("BTCUSDT", "SELL", 0.8, None)
    assert result is not None
    side, quote, meta = result
    assert side == "SELL"
    assert abs(meta["score"]) > 0.5  # Should have reasonable score
