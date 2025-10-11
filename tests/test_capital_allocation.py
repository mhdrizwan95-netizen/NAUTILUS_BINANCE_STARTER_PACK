"""
Test Capital Allocation System

Validates dynamic capital allocation and quota enforcement.
"""
import json
import asyncio
import pytest
from pathlib import Path
from ops.capital_allocator import get_model_quota, simulate_allocation_cycle
from ops.capital_policy import *


class TestCapitalAllocation:
    """Test suite for capital allocation functionality."""

    @pytest.fixture
    def temp_allocations_file(self, tmp_path):
        """Create a temporary allocations file."""
        alloc_file = tmp_path / "capital_allocations.json"
        allocations = {
            "capital_quota_usd": {
                "hmm_v2_canary": 5000.0,
                "ma_crossover_v3": 3000.0
            },
            "updated_at": {"hmm_v2_canary": 1234567890, "ma_crossover_v3": 1234567890},
            "equity_usd": 100000.0,
            "ts": 1234567890
        }
        alloc_file.write_text(json.dumps(allocations, indent=2))
        return alloc_file

    def test_get_model_quota(self, temp_allocations_file, monkeypatch):
        """Test quota retrieval for a model."""
        monkeypatch.setattr("ops.capital_allocator.ALLOCATIONS_PATH", temp_allocations_file)

        quota = get_model_quota("hmm_v2_canary")
        assert quota == 5000.0

        quota_missing = get_model_quota("nonexistent_model")
        assert quota_missing == 0.0

    @pytest.mark.asyncio
    async def test_simulate_allocation_cycle(self):
        """Test allocation simulation with test data."""
        test_policy = {
            "enabled": ["alpha", "beta"],
            "base_equity_frac": 0.2,
            "min_quota_usd": 1000.0,
            "max_quota_usd": 10000.0,
            "sharpe_promote": 1.5,
            "sharpe_demote": 0.3,
            "step_up_pct": 0.25,
            "step_down_pct": 0.2,
            "cooldown_sec": 0  # No cooldown for testing
        }

        test_metrics = {
            "portfolio_equity_usd": 100000.0,
            "models": {
                "alpha": {"sharpe": 2.0, "realized_pnl": 1000.0},  # Should promote
                "beta": {"sharpe": 0.2, "realized_pnl": -500.0}   # Should demote
            }
        }

        result = await simulate_allocation_cycle(test_policy, test_metrics)

        assert result["policy"] == test_policy
        assert result["equity"] == 100000.0
        assert "alpha" in result["final_quotas"]
        assert "beta" in result["final_quotas"]
        assert result["final_quotas"]["alpha"] > result["final_quotas"]["beta"]

    def test_quota_bounds_enforcement(self):
        """Test that quota bounds are properly enforced."""
        from ops.capital_allocator import calculate_target_allocation

        policy = {
            "enabled": ["test_model"],
            "base_equity_frac": 0.5,
            "min_quota_usd": 1000.0,
            "max_quota_usd": 5000.0,
            "sharpe_promote": 1.0,
            "sharpe_demote": 0.5,
            "step_up_pct": 1.0,  # Should result in quota exceeding max
            "step_down_pct": 0.5,
            "cooldown_sec": 0
        }

        equity = 10000.0
        models = {"test_model": {"sharpe": 2.0}}  # High Sharpe to trigger promotion

        # Simulate with current allocations starting at max
        import ops.capital_allocator
        original_load = ops.capital_allocator.load_json
        def mock_load_json(path, default=None):
            if path.name == "capital_allocations.json":
                return {
                    "capital_quota_usd": {"test_model": 5000.0},  # At max
                    "updated_at": {"test_model": 0}
                }
            return original_load(path, default)

        ops.capital_allocator.load_json = mock_load_json
        ops.capital_allocator.save_json = lambda *args: None  # No-op

        try:
            target_allocations = calculate_target_allocation(policy, equity, models)
            quota = target_allocations["test_model"]["target_quota"]
            assert quota <= policy["max_quota_usd"], f"Quota {quota} exceeds max {policy['max_quota_usd']}"
            assert quota >= policy["min_quota_usd"], f"Quota {quota} below min {policy['min_quota_usd']}"
        finally:
            ops.capital_allocator.load_json = original_load

if __name__ == "__main__":
    pytest.main([__file__])
