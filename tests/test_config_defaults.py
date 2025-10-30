from __future__ import annotations

import pytest

from engine.config.defaults import ALL_DEFAULTS, GLOBAL_DEFAULTS
from engine.config.env import split_symbols
from engine.strategies.trend_follow import load_trend_config


def test_split_symbols_allows_wildcard():
    assert split_symbols("*") is None
    assert split_symbols("") is None
    assert split_symbols("BTCUSDT, ETHUSDT") == ["BTCUSDT", "ETHUSDT"]


def test_trend_config_falls_back_to_global_symbols(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TREND_SYMBOLS", raising=False)
    monkeypatch.setenv("TRADE_SYMBOLS", "*")
    cfg = load_trend_config()
    assert cfg.symbols == []


def test_all_defaults_have_values():
    for key, value in ALL_DEFAULTS.items():
        assert value is not None, f"Default for {key} should not be None"


@pytest.mark.parametrize("key", ["TRADE_SYMBOLS", "DRY_RUN"])
def test_global_defaults_present(key: str):
    assert key in GLOBAL_DEFAULTS
