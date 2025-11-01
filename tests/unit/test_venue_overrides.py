import types

from engine.execution.venue_overrides import VenueOverrides


def test_mute_on_slippage_skips(monkeypatch):
    clock = types.SimpleNamespace(time=lambda: 1_700_000_000.0)
    ov = VenueOverrides(clock=clock)
    # thresholds: 3 in 10m
    sym = "AAAUSDT"
    assert ov.scalp_enabled(sym)
    for _ in range(3):
        ov.record_skip(sym, "slippage")
    assert ov.scalp_enabled(sym) is False


def test_size_cutback_on_avg_slippage(monkeypatch):
    clock = types.SimpleNamespace(time=lambda: 1_700_000_000.0)
    ov = VenueOverrides(clock=clock)
    sym = "BBBUSDT"
    # Feed 5 samples over window above 15 bps cap
    for bps in [20, 18, 22, 25, 19]:
        ov.record_slippage_sample(sym, bps)
    mult = ov.get_size_mult(sym)
    assert mult <= 0.5 + 1e-9  # cutback applied (default 0.5)
