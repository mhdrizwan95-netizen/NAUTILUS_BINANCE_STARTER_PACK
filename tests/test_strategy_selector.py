import json
from pathlib import Path

import pytest

from ops import strategy_selector


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


@pytest.fixture
def selector_env(tmp_path, monkeypatch):
    registry_path = tmp_path / "strategy_registry.json"
    weights_path = tmp_path / "strategy_weights.json"
    policy_path = tmp_path / "m25_policy.yaml"
    audit_path = tmp_path / "logs" / "promotion_audit.jsonl"
    risk_snapshot = tmp_path / "metrics_snapshot.json"

    registry = {
        "current_model": "stable_model",
        "stable_model": {
            "sharpe": 1.2,
            "drawdown": 0.1,
            "samples": 10,
            "trades": 200,
        },
        "canary_model": {
            "sharpe": 1.4,
            "drawdown": 0.05,
            "samples": 12,
            "trades": 210,
        },
    }
    _write_json(registry_path, registry)

    weights = {
        "current": "stable_model",
        "weights": {"stable_model": 0.8, "canary_model": 0.2},
        "max_canary_weight": 0.2,
    }
    _write_json(weights_path, weights)

    policy_path.write_text(
        "human_review:\n  require_approval_for_promotion: true\n"
        "risk_limits:\n  max_daily_loss_usd: 9999\n  max_position_usd: 999999\n"
        "  max_leverage: 10\n  max_open_trades: 100\n"
    )
    _write_json(risk_snapshot, {})

    monkeypatch.setattr(strategy_selector, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(strategy_selector, "WEIGHTS_PATH", weights_path)
    monkeypatch.setattr(strategy_selector, "POLICY_PATH", policy_path)
    monkeypatch.setattr(strategy_selector, "PROMOTION_AUDIT_PATH", audit_path)
    monkeypatch.setattr(strategy_selector, "RISK_SNAPSHOT_PATH", risk_snapshot)
    monkeypatch.setattr(strategy_selector, "_append_promotion_audit", lambda *_: None)
    monkeypatch.setattr(
        strategy_selector,
        "_compliance_allows_promotion",
        lambda: (True, []),
    )
    yield registry_path, weights_path


def test_promotion_requires_human_approval(selector_env):
    registry_path, weights_path = selector_env

    strategy_selector.promote_best()

    registry = json.loads(registry_path.read_text())
    weights = json.loads(weights_path.read_text())

    assert registry["current_model"] == "stable_model"
    assert "pending_promotions" in registry
    assert "canary_model" in registry["pending_promotions"]
    assert weights["weights"]["stable_model"] == pytest.approx(0.8)
    assert weights["weights"]["canary_model"] == pytest.approx(0.2)


def test_promotion_applies_staged_weights_after_approval(selector_env):
    registry_path, weights_path = selector_env

    registry = json.loads(registry_path.read_text())
    registry["canary_model"]["approved"] = True
    _write_json(registry_path, registry)

    strategy_selector.promote_best()

    updated_registry = json.loads(registry_path.read_text())
    updated_weights = json.loads(weights_path.read_text())

    assert updated_registry["current_model"] == "canary_model"
    assert (
        "pending_promotions" not in updated_registry or not updated_registry["pending_promotions"]
    )
    assert updated_weights["weights"]["canary_model"] == pytest.approx(1.0)
    assert updated_weights["weights"]["stable_model"] == pytest.approx(0.0)
