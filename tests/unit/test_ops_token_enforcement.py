import importlib
import os
import sys

import pytest


def _reload(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_ops_api_requires_secret(monkeypatch):
    monkeypatch.delenv("OPS_API_TOKEN", raising=False)
    monkeypatch.delenv("OPS_API_TOKEN_FILE", raising=False)
    sys.modules.pop("ops.ops_api", None)

    with pytest.raises(RuntimeError):
        importlib.import_module("ops.ops_api")

    monkeypatch.setenv("OPS_API_TOKEN", "unit-test-token-1234567890")
    mod = _reload("ops.ops_api")
    assert mod.EXPECTED_TOKEN == "unit-test-token-1234567890"

    # Restore default for subsequent tests
    monkeypatch.setenv("OPS_API_TOKEN", "test-ops-token-1234567890")
    mod = _reload("ops.ops_api")
    assert mod.EXPECTED_TOKEN == "test-ops-token-1234567890"


def test_ops_ui_requires_secret(monkeypatch):
    monkeypatch.delenv("OPS_API_TOKEN", raising=False)
    monkeypatch.delenv("OPS_API_TOKEN_FILE", raising=False)
    sys.modules.pop("ops.ops_api", None)
    sys.modules.pop("ops.ui_api", None)

    with pytest.raises(RuntimeError):
        importlib.import_module("ops.ui_api")

    monkeypatch.setenv("OPS_API_TOKEN", "unit-test-token-2234567890")
    ui_mod = _reload("ops.ui_api")
    assert ui_mod.OPS_TOKEN == "unit-test-token-2234567890"
    assert ui_mod.WS_TOKEN == "unit-test-token-2234567890"

    # Restore default for subsequent tests
    monkeypatch.setenv("OPS_API_TOKEN", "test-ops-token-1234567890")
    ui_mod = _reload("ops.ui_api")
    assert ui_mod.OPS_TOKEN == "test-ops-token-1234567890"
    assert ui_mod.WS_TOKEN == "test-ops-token-1234567890"
