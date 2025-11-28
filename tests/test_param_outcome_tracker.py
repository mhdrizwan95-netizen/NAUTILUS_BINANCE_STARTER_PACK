import pytest

from engine.services.param_client import ParamOutcomeTracker


@pytest.fixture
def tracker():
    return ParamOutcomeTracker()


def test_tracker_realizes_long_positions(tracker):
    assert tracker.process("hmm", "BTCUSDT", "preset-a", "BUY", 1.0, 100.0) == 0.0
    gain = tracker.process("hmm", "BTCUSDT", "preset-a", "SELL", 0.4, 105.0)
    assert pytest.approx(gain, rel=1e-9) == 2.0
    loss = tracker.process("hmm", "BTCUSDT", "preset-a", "SELL", 0.6, 95.0)
    assert pytest.approx(loss, rel=1e-9) == -3.0


def test_tracker_handles_flips(tracker):
    assert tracker.process("hmm", "ETHUSDT", "preset-a", "SELL", 1.0, 50.0) == 0.0
    gain = tracker.process("hmm", "ETHUSDT", "preset-a", "BUY", 0.25, 45.0)
    assert pytest.approx(gain, rel=1e-9) == 1.25
    tracker.process("hmm", "ETHUSDT", "preset-a", "BUY", 1.25, 48.0)
    # Position flips to long 0.5 @ 48; closing part should produce realized PnL
    closing = tracker.process("hmm", "ETHUSDT", "preset-a", "SELL", 0.5, 55.0)
    assert pytest.approx(closing, rel=1e-9) == (55.0 - 48.0) * 0.5
