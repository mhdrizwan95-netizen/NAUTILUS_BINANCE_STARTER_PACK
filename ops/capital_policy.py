"""
Capital Policy helpers

Centralised utilities for reading and updating the capital allocation
policy JSON file that governs how much equity each model may deploy.
Keeping this logic in one place ensures that tests and runtime services
operate on the same canonical defaults.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CAPITAL_POLICY_PATH = Path("ops/capital_policy.json")

DEFAULT_POLICY: dict[str, Any] = {
    "refresh_sec": 30,
    "base_equity_frac": 0.20,
    "min_pool_usd": 10000.0,
    "reserve_equity_usd": 5000.0,
    "min_quota_usd": 250.0,
    "max_quota_usd": 25000.0,
    "step_up_pct": 0.15,
    "step_down_pct": 0.20,
    "sharpe_promote": 1.00,
    "sharpe_demote": 0.30,
    "cooldown_sec": 900,
    "enabled": ["ma_crossover_v3", "hmm_v2_canary"],
    "allocation_mode": "dynamic",
    "fallback_mode": "equal_split",
}

log = logging.getLogger(__name__)
_JSON_ERRORS = (OSError, json.JSONDecodeError)


def load_capital_policy(path: Path | None = None, *, create: bool = True) -> dict[str, Any]:
    """
    Load the capital policy from disk.

    Args:
        path: Optional custom path. Defaults to `CAPITAL_POLICY_PATH`.
        create: When True and the file is missing, persist `DEFAULT_POLICY`.

    Returns:
        Dict with the capital policy parameters.
    """
    policy_path = path or CAPITAL_POLICY_PATH
    if not policy_path.exists():
        if create:
            save_capital_policy(DEFAULT_POLICY, policy_path)
        return DEFAULT_POLICY.copy()

    try:
        return json.loads(policy_path.read_text())
    except _JSON_ERRORS as exc:  # pragma: no cover - logged and fallback for resilience
        log.warning("Failed to load %s (%s). Using defaults.", policy_path, exc)
        return DEFAULT_POLICY.copy()


def save_capital_policy(policy: dict[str, Any], path: Path | None = None) -> None:
    """
    Persist the provided capital policy atomically.
    """
    policy_path = path or CAPITAL_POLICY_PATH
    tmp_path = policy_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(policy, indent=2, sort_keys=True))
    tmp_path.replace(policy_path)


def ensure_policy_file(path: Path | None = None) -> Path:
    """
    Ensure the capital policy exists on disk and return the resolved path.
    """
    policy_path = path or CAPITAL_POLICY_PATH
    if not policy_path.exists():
        save_capital_policy(DEFAULT_POLICY, policy_path)
    return policy_path


def enabled_models(policy: dict[str, Any] | None = None) -> list[str]:
    """
    Return the list of models enabled by the current policy.
    """
    policy = policy or load_capital_policy(create=True)
    enabled = policy.get("enabled", [])
    if isinstance(enabled, dict):
        # Some legacy policies stored enabled models as {"model": true}
        return [name for name, enabled_flag in enabled.items() if enabled_flag]
    if isinstance(enabled, Iterable):
        return [str(item) for item in enabled]
    return []


def is_model_enabled(model_name: str, policy: dict[str, Any] | None = None) -> bool:
    """
    Convenience helper to check if a strategy is currently enabled.
    """
    return model_name in enabled_models(policy)


def update_enabled_models(models: Iterable[str], *, merge: bool = True) -> dict[str, Any]:
    """
    Update the enabled models list. When merge is True we union with existing models,
    otherwise we replace the list entirely.
    """
    current = load_capital_policy(create=True)
    new_models = {str(name) for name in models}
    if merge:
        new_models.update(enabled_models(current))
    current["enabled"] = sorted(new_models)
    save_capital_policy(current)
    return current


__all__ = [
    "CAPITAL_POLICY_PATH",
    "DEFAULT_POLICY",
    "ensure_policy_file",
    "enabled_models",
    "is_model_enabled",
    "load_capital_policy",
    "save_capital_policy",
    "update_enabled_models",
]
