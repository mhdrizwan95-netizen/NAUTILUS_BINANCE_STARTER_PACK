import os
from typing import Dict, List

import pytest

from engine.universe.effective import StrategyUniverse


class DummyScanner:
    def __init__(self, mapping: Dict[str, List[str]]):
        self.mapping = mapping

    def current_universe(self, strategy: str) -> List[str]:
        return list(self.mapping.get(strategy, []))


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SYMBOL_SCANNER_ENABLED", raising=False)
    monkeypatch.delenv("TRADE_SYMBOLS", raising=False)
    yield


def test_scanner_overrides_global(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYMBOL_SCANNER_ENABLED", "true")
    monkeypatch.setenv("TRADE_SYMBOLS", "BTCUSDT,ETHUSDT")
    scanner = DummyScanner({"trend": ["XRPUSDT", "SOLUSDT"]})
    universe = StrategyUniverse(scanner)
    assert universe.get("trend") == ["SOLUSDT", "XRPUSDT"]


def test_fallback_to_global_allowlist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYMBOL_SCANNER_ENABLED", "false")
    monkeypatch.setenv("TRADE_SYMBOLS", "BTCUSDT,ETHUSDT")
    universe = StrategyUniverse(None)
    assert universe.get("trend") == ["BTCUSDT", "ETHUSDT"]


def test_wildcard_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SYMBOL_SCANNER_ENABLED", "0")
    monkeypatch.setenv("TRADE_SYMBOLS", "*")
    universe = StrategyUniverse(None)
    assert universe.get("trend") is None
