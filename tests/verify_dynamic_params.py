import json
import logging
from pathlib import Path
from unittest.mock import patch

from engine.strategies.trend_follow import TrendStrategyConfig, TrendStrategyModule, TrendTF

# Configure logging
logging.basicConfig(level=logging.INFO)


def get_trend_config(auto_tune=True):
    return TrendStrategyConfig(
        enabled=True,
        dry_run=True,
        symbols=["BTCUSDT"],
        fetch_limit=100,
        refresh_sec=60,
        atr_length=14,
        atr_stop_mult=2.0,
        atr_target_mult=3.0,
        swing_lookback=20,
        rsi_long_min=40.0,
        rsi_long_max=100.0,
        rsi_exit=80.0,
        risk_pct=0.01,
        min_quote_usd=10.0,
        fallback_equity_usd=1000.0,
        cooldown_bars=1,
        allow_shorts=False,
        auto_tune_enabled=auto_tune,
        auto_tune_min_trades=2,  # Small for testing
        auto_tune_interval=1,  # Update after every trade
        auto_tune_history=10,
        auto_tune_win_low=0.4,
        auto_tune_win_high=0.6,
        auto_tune_stop_min=1.0,
        auto_tune_stop_max=5.0,
        auto_tune_state_path="/tmp/trend_auto_tune_test.json",
        primary=TrendTF(interval="15m", fast=10, slow=20, rsi_length=14),
        secondary=TrendTF(interval="1h", fast=10, slow=20, rsi_length=14),
        regime=TrendTF(interval="4h", fast=10, slow=20, rsi_length=14),
    )


def test_auto_tune_losses():
    print("\n=== Testing Auto-Tune (Losses) ===")
    cfg = get_trend_config()
    # Clean up state file
    Path(cfg.auto_tune_state_path).unlink(missing_ok=True)

    strategy = TrendStrategyModule(cfg)
    initial_stop = strategy._params.atr_stop_mult
    print(f"Initial Stop Mult: {initial_stop}")

    # Simulate 3 losing trades
    # Win rate = 0/3 = 0.0 < 0.4 (win_low) -> Should adjust for losses
    # Adjust for losses: increases stop mult

    for i in range(3):
        strategy._record_trade("BTCUSDT", -0.10, 100.0, {})  # -10% loss

    new_stop = strategy._params.atr_stop_mult
    print(f"New Stop Mult: {new_stop}")

    if new_stop > initial_stop:
        print("SUCCESS: Stop multiplier increased after losses.")
    else:
        print(f"FAILURE: Stop multiplier did not increase. {initial_stop} -> {new_stop}")


def test_auto_tune_wins():
    print("\n=== Testing Auto-Tune (Wins) ===")
    cfg = get_trend_config()
    # Clean up state file
    Path(cfg.auto_tune_state_path).unlink(missing_ok=True)

    strategy = TrendStrategyModule(cfg)
    # Set high initial stop to allow room for decrease
    strategy._params.atr_stop_mult = 4.0
    initial_stop = strategy._params.atr_stop_mult
    print(f"Initial Stop Mult: {initial_stop}")

    # Simulate 3 winning trades
    # Win rate = 3/3 = 1.0 > 0.6 (win_high) -> Should adjust for wins
    # Adjust for wins: decreases stop mult (tightens stops)

    for i in range(3):
        strategy._record_trade("BTCUSDT", 0.10, 100.0, {})  # +10% win

    new_stop = strategy._params.atr_stop_mult
    print(f"New Stop Mult: {new_stop}")

    if new_stop < initial_stop:
        print("SUCCESS: Stop multiplier decreased after wins.")
    else:
        print(f"FAILURE: Stop multiplier did not decrease. {initial_stop} -> {new_stop}")


def test_calibration_reload():
    print("\n=== Testing Calibration Reload ===")

    from engine.strategies import calibration

    # Create temp calibration file
    cal_path = Path("/tmp/hmm_calibration_test.json")
    cal_path.write_text(json.dumps({"BTCUSDT": {"cooldown_scale": 2.0}}))

    # Patch the path in calibration module
    with patch("engine.strategies.calibration.CALIBRATION_PATH", cal_path):
        # Force cache expiry
        calibration._cache["ts"] = 0

        scale = calibration.cooldown_scale("BTCUSDT")
        print(f"Scale (Initial): {scale}")

        if scale == 2.0:
            print("SUCCESS: Loaded initial calibration.")
        else:
            print(f"FAILURE: Expected 2.0, got {scale}")

        # Update file
        cal_path.write_text(json.dumps({"BTCUSDT": {"cooldown_scale": 5.0}}))

        # Force cache expiry again
        calibration._cache["ts"] = 0

        new_scale = calibration.cooldown_scale("BTCUSDT")
        print(f"Scale (Updated): {new_scale}")

        if new_scale == 5.0:
            print("SUCCESS: Loaded updated calibration.")
        else:
            print(f"FAILURE: Expected 5.0, got {new_scale}")


if __name__ == "__main__":
    test_auto_tune_losses()
    test_auto_tune_wins()
    test_calibration_reload()
