import math

from engine.metrics import generate_latest
from engine.strategies.momentum_realtime import (
    MomentumRealtimeConfig,
    MomentumStrategyModule,
)


def _module_config(**overrides):
    base = dict(
        enabled=True,
        dry_run=True,
        symbols=("ABCUSDT",),
        window_sec=30.0,
        baseline_sec=120.0,
        min_ticks=2,
        pct_move_threshold=0.02,
        volume_spike_ratio=1.5,
        cooldown_sec=90.0,
        quote_usd=100.0,
        stop_loss_pct=0.01,
        trail_pct=0.015,
        take_profit_pct=0.04,
        allow_shorts=False,
        prefer_futures=True,
    )
    base.update(overrides)
    return MomentumRealtimeConfig(**base)


def test_momentum_rt_breakout_signal_generates_order():
    cfg = _module_config()
    module = MomentumStrategyModule(cfg)

    # Baseline ticks to seed history (older than fast window)
    module.handle_tick("ABCUSDT.BINANCE", 100.0, ts=0.0, volume=40.0)
    module.handle_tick("ABCUSDT.BINANCE", 100.6, ts=35.0, volume=45.0)

    signal = module.handle_tick("ABCUSDT.BINANCE", 103.2, ts=65.0, volume=220.0)
    assert signal is not None
    assert signal["side"] == "BUY"
    assert signal["symbol"] == "ABCUSDT.BINANCE"
    assert math.isclose(signal["quote"], cfg.quote_usd)
    assert signal["market"] == "futures"
    meta = signal["meta"]
    assert math.isclose(
        meta["stop_price"], 103.2 * (1 - cfg.stop_loss_pct), rel_tol=1e-6
    )
    assert math.isclose(meta["trail_distance"], 103.2 * cfg.trail_pct, rel_tol=1e-6)
    assert math.isclose(
        meta["take_profit"], 103.2 * (1 + cfg.take_profit_pct), rel_tol=1e-6
    )
    metrics_blob = generate_latest().decode()
    assert "momentum_rt_breakouts_total" in metrics_blob
    assert "momentum_rt_cooldown_epoch" in metrics_blob

    # Cooldown should block immediate repeat
    again = module.handle_tick("ABCUSDT.BINANCE", 104.0, ts=80.0, volume=180.0)
    assert again is None


def test_momentum_rt_short_signal_when_enabled():
    cfg = _module_config(allow_shorts=True)
    module = MomentumStrategyModule(cfg)

    module.handle_tick("ABCUSDT.BINANCE", 110.0, ts=0.0, volume=60.0)
    module.handle_tick("ABCUSDT.BINANCE", 109.5, ts=50.0, volume=55.0)

    signal = module.handle_tick("ABCUSDT.BINANCE", 104.5, ts=75.0, volume=250.0)
    assert signal is not None
    assert signal["side"] == "SELL"
    assert signal["market"] == "futures"
    meta = signal["meta"]
    assert math.isclose(
        meta["stop_price"], 104.5 * (1 + cfg.stop_loss_pct), rel_tol=1e-6
    )
    assert math.isclose(
        meta["take_profit"], 104.5 * (1 - cfg.take_profit_pct), rel_tol=1e-6
    )
    assert math.isclose(meta["trail_distance"], 104.5 * cfg.trail_pct, rel_tol=1e-6)
