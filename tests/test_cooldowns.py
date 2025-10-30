from engine.state.cooldown import Cooldowns


def test_cooldown_basic() -> None:
    tracker = Cooldowns(default_ttl=1.0)
    key = "BTCUSDT"

    assert tracker.allow(key)
    tracker.hit(key, now=0.0)
    assert not tracker.allow(key, now=0.1)
    assert tracker.allow(key, now=1.1)

    remaining = tracker.remaining(key, now=0.1)
    assert 0.89 < remaining < 0.91

    tracker.clear(key)
    assert tracker.allow(key, now=0.1)

    tracker.hit(key, ttl=2.0, now=5.0)
    assert not tracker.allow(key, now=6.0)
    assert tracker.allow(key, now=7.1)
