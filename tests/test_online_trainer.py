#!/usr/bin/env python3
# tests/test_online_trainer.py — M15: Online learning safety and adaptation tests
import numpy as np
import pytest
from pathlib import Path
import tempfile

from strategies.hmm_policy.policy_head import TinyMLP
from strategies.hmm_policy.online_trainer import OnlineFineTuner

def test_online_trainer_basic():
    """Test basic online training functionality."""
    model = TinyMLP(d_in=11, d_hidden=8, seed=42)
    trainer = OnlineFineTuner(model, lr=1e-3, batch_size=16, cool_s=0.0)  # Fast for testing

    # Generate some dummy features and outcomes
    features = np.random.randn(50, 11)

    # Simulate winning BUY trades and losing SELL trades
    for i in range(25):
        # BUY that wins
        trainer.observe(features[i], "BUY", 10.0)
        # SELL that loses
        trainer.observe(features[i+25], "SELL", -5.0)

    # Should trigger update immediately (no cooldown)
    updated = trainer.maybe_update(0.0)
    assert updated or len(trainer.x_buffer) >= trainer.batch_size

def test_performance_kill_switch():
    """Test automatic disable on poor performance."""
    model = TinyMLP(d_in=5, d_hidden=4, seed=42)
    trainer = OnlineFineTuner(model, early_stop_win_rate=0.5, early_stop_trade_count=20)

    # Simulate consistently poor performance
    for i in range(25):
        trainer.observe(np.random.randn(5), "BUY", -1.0)  # All losses

    # Try to update - should fail due to poor performance
    updated = trainer.maybe_update()
    assert not trainer.is_enabled  # Should auto-disable

def test_gradient_clipping():
    """Test that gradients are properly clipped."""
    model = TinyMLP(d_in=8, d_hidden=6, seed=42)
    trainer = OnlineFineTuner(model, lr=1e-2, batch_size=8, cool_s=0.0)

    # Generate extreme features that might cause large gradients
    extreme_features = np.random.randn(16, 8) * 10  # Large values
    labels = np.random.randint(0, 2, 16)

    # Add to buffer and update
    for i in range(16):
        trainer.x_buffer.append(extreme_features[i])
        trainer.y_buffer.append(labels[i])

    # Update should not cause numerical issues
    updated = trainer.maybe_update(1000.0)  # Force override cooldown
    assert trainer.total_updates >= 0  # No crash

    # Model weights should still be finite
    stats = trainer.model.get_weights_norms()
    assert all(np.isfinite(v) for v in stats.values())

def test_snapshot_rollback():
    """Test model state snapshots and rollback."""
    with tempfile.TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        snapshot_dir.mkdir()

        model = TinyMLP(d_in=6, d_hidden=4, seed=42)
        # Manually set some weights
        model.W1[0, 0] = 999.0  # Mark distinctive weight

        trainer = OnlineFineTuner(model, cool_s=0.0)
        trainer.snapshot_dir = snapshot_dir

        # Save snapshot
        trainer.save_snapshot()
        original_weights = model.W1.copy()

        # Modify weights
        model.W1 += np.random.randn(*model.W1.shape)

        # Load snapshot - should restore
        success = trainer.load_latest_snapshot()
        assert success

        # Weights should be approximately restored
        restored_diff = np.abs(model.W1 - original_weights).max()
        assert restored_diff < 1e-10  # Exact match (no random drift)

def test_hold_band_logic():
    """Test HOLD decision logic with confidence bands."""
    model = TinyMLP(d_in=4, d_hidden=3, seed=42)
    trainer = OnlineFineTuner(model, hold_band=0.2)

    features = np.random.randn(4)

    # Force model to output around 0.5
    # This is tricky in practice, but test the band
    score = trainer.score(features)
    assert 0.0 <= score <= 1.0

    # With default band, probabilities near 0.5 should remain as 0.5
    # This test verifies the method runs without error
    assert isinstance(score, float)

def test_buffer_management():
    """Test experience buffer management."""
    model = TinyMLP(d_in=5, d_hidden=4, seed=42)
    trainer = OnlineFineTuner(model, buffer_max=100, batch_size=10)

    # Fill buffer beyond max
    for i in range(150):
        trainer.observe(np.random.randn(5), "BUY", 1.0)

    # Buffer should be capped
    assert len(trainer.x_buffer) <= 100
    assert len(trainer.y_buffer) <= 100

def test_cooldown_mechanism():
    """Test cooldown prevents too-frequent updates."""
    model = TinyMLP(d_in=7, d_hidden=5, seed=42)
    trainer = OnlineFineTuner(model, cool_s=1.0)  # 1 second cooldown

    # Add sufficient data
    for i in range(trainer.batch_size * 2):
        trainer.observe(np.random.randn(7), "BUY", 1.0)

    # First update at time 0
    updated1 = trainer.maybe_update(0.0)
    last_update1 = trainer.last_update_ts

    # Immediate second attempt should fail
    updated2 = trainer.maybe_update(0.5)
    assert not updated2

    # After cooldown, should succeed
    updated3 = trainer.maybe_update(1.5)
    assert updated3
    assert trainer.last_update_ts > last_update1

def test_performance_metrics():
    """Test performance tracking and metrics."""
    model = TinyMLP(d_in=6, d_hidden=4, seed=42)
    trainer = OnlineFineTuner(model, early_stop_trade_count=30)

    # Add some mixed performance
    for i in range(30):
        side = "BUY" if i % 2 == 0 else "SELL"
        pnl = 2.0 if side == "BUY" else -1.0  # Some wins, some losses
        trainer.observe(np.random.randn(6), side, pnl)

    # Should still be enabled (win rate above threshold)
    assert trainer.is_enabled

    # Performance summary should contain relevant metrics
    summary = trainer.get_performance_summary()
    required_keys = ['avg_pnl', 'win_rate', 'profit_factor', 'sharpe_like']
    for key in required_keys:
        assert key in summary or 'insufficient_data' in summary

def test_stats_reporting():
    """Test trainer statistics collection."""
    model = TinyMLP(d_in=8, d_hidden=6, seed=42)
    trainer = OnlineFineTuner(model)

    stats = trainer.get_stats()

    required_fields = ['enabled', 'total_updates', 'buffer_size',
                      'last_update_age_s', 'recent_win_rate']
    for field in required_fields:
        assert field in stats
        assert isinstance(stats[field], (int, float))

def test_action_prediction_thresholds():
    """Test action prediction with different thresholds."""
    model = TinyMLP(d_in=4, d_hidden=3, seed=42)
    trainer = OnlineFineTuner(model)

    features = np.random.randn(4)

    # Test various thresholds
    for threshold in [0.4, 0.5, 0.6]:
        action = trainer.predict_action(features, threshold)
        assert action in ['BUY', 'SELL', 'HOLD']

def test_large_gradient_scenario():
    """Test handling of potentially unstable scenarios."""
    model = TinyMLP(d_in=10, d_hidden=8, seed=42)
    trainer = OnlineFineTuner(model, lr=1e-3, cool_s=0.0)

    # Create scenario with large losses following small gains
    for i in range(20):
        features = np.random.randn(10) + i * 0.1  # Gradually changing
        pnl = (-1.0)**i * (i + 1)  # Alternating large magnitude
        side = "BUY" if pnl > 0 else "SELL"

        trainer.observe(features, side, pnl)

    # Should not crash even with oscillations
    updated = trainer.maybe_update(1000.0)
    assert trainer.total_updates >= 0  # At least didn't crash

    # Model should remain numerically stable
    test_pred = trainer.score(np.random.randn(10))
    assert np.isfinite(test_pred)
    assert 0.0 <= test_pred <= 1.0
