import json
from pathlib import Path

import pytest

from ops import capital_allocator as allocator


def test_calculate_target_allocation_updates_cooldown(monkeypatch, tmp_path):
    alloc_path = Path(tmp_path) / "allocations.json"
    alloc_path.write_text(
        json.dumps({"capital_quota_usd": {"modelA": 200.0}, "updated_at": {"modelA": 0}})
    )
    monkeypatch.setattr(allocator, "ALLOCATIONS_PATH", alloc_path)

    frozen_now = 1_000.0
    monkeypatch.setattr(allocator.time, "time", lambda: frozen_now)

    policy = {
        "enabled": ["modelA"],
        "cooldown_sec": 60,
        "base_equity_frac": 0.2,
        "min_quota_usd": 100.0,
        "max_quota_usd": 1000.0,
        "step_up_pct": 0.10,
        "step_down_pct": 0.10,
        "sharpe_promote": 1.0,
        "sharpe_demote": 0.0,
    }
    metrics = {
        "portfolio_equity_usd": 50000.0,
        "models": {"modelA": {"sharpe": 1.5, "realized_pnl": 1200.0}},
    }

    allocations = allocator.calculate_target_allocation(
        policy, 50000.0, metrics["models"]
    )
    entry = allocations["modelA"]

    assert entry["decision"] == "promote"
    assert entry["last_update"] == pytest.approx(frozen_now)
    assert entry["next_update"] == pytest.approx(frozen_now + policy["cooldown_sec"])
