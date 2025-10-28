from __future__ import annotations

from pathlib import Path

import pytest

from engine.runtime.config import (
    RuntimeConfig,
    load_runtime_config,
)


def test_load_runtime_config_defaults(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RUNTIME_CONFIG_PATH", raising=False)
    cfg = load_runtime_config(path=tmp_path / "missing.yaml")
    assert isinstance(cfg, RuntimeConfig)
    assert cfg.risk.max_concurrent == 5
    assert cfg.buckets.total == 1.0


def test_load_runtime_config_file(tmp_path: Path, monkeypatch):
    runtime_yaml = tmp_path / "runtime.yaml"
    runtime_yaml.write_text(
        """
risk:
  per_trade_pct:
    trend: 0.03
  max_concurrent: 3
  daily_stop_pct: 0.04
buckets:
  futures_core: 0.5
  spot_margin: 0.3
  event: 0.1
  reserve: 0.1
bus:
  max_queue: 2048
  signal_ttl_seconds: 30
demo_mode: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNTIME_CONFIG_PATH", str(runtime_yaml))
    cfg = load_runtime_config()
    assert cfg.demo_mode is True
    assert cfg.risk.per_trade_pct["trend"] == 0.03
    assert cfg.risk.max_concurrent == 3
    assert cfg.bus.max_queue == 2048


def test_runtime_config_preserves_default_leverage(tmp_path: Path, monkeypatch):
    runtime_yaml = tmp_path / "runtime.yaml"
    runtime_yaml.write_text(
        """
futures:
  leverage:
    BTCUSDT: 7
    default: 2
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("RUNTIME_CONFIG_PATH", raising=False)
    cfg = load_runtime_config(path=runtime_yaml)
    assert cfg.futures.leverage["BTCUSDT"] == 7
    assert cfg.futures.leverage.get("DEFAULT") == 2


def test_runtime_config_futures_leverage_overrides(tmp_path: Path, monkeypatch):
    runtime_yaml = tmp_path / "runtime.yaml"
    runtime_yaml.write_text(
        """
futures:
  futures_leverage:
    btcusdt: default
    ETHUSDT: 12
    solusdt: Default
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("RUNTIME_CONFIG_PATH", raising=False)
    cfg = load_runtime_config(path=runtime_yaml)
    overrides = cfg.futures.desired_leverage
    assert overrides["BTCUSDT"] is None
    assert overrides["SOLUSDT"] is None
    assert overrides["ETHUSDT"] == 12


def test_runtime_config_futures_leverage_invalid(tmp_path: Path, monkeypatch):
    runtime_yaml = tmp_path / "runtime.yaml"
    runtime_yaml.write_text(
        """
futures:
  futures_leverage:
    BTCUSDT: 0
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("RUNTIME_CONFIG_PATH", raising=False)
    with pytest.raises(ValueError):
        load_runtime_config(path=runtime_yaml)
