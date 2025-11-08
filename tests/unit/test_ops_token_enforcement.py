import importlib
import sys

import pytest


def test_ops_api_requires_secret(monkeypatch):
    monkeypatch.delenv("OPS_API_TOKEN", raising=False)
    monkeypatch.delenv("OPS_API_TOKEN_FILE", raising=False)
    sys.modules.pop("ops.ops_api", None)

    mod = importlib.import_module("ops.ops_api")
    with pytest.raises(RuntimeError):
        mod.get_expected_token()

    mod.reset_expected_token_cache()
    monkeypatch.setenv("OPS_API_TOKEN", "unit-test-token-1234567890")
    mod.reset_expected_token_cache()
    assert mod.get_expected_token() == "unit-test-token-1234567890"

    # Restore default for subsequent tests
    monkeypatch.setenv("OPS_API_TOKEN", "test-ops-token-1234567890")
    mod.reset_expected_token_cache()
    assert mod.get_expected_token() == "test-ops-token-1234567890"


def test_ops_ui_requires_secret(monkeypatch):
    monkeypatch.delenv("OPS_API_TOKEN", raising=False)
    monkeypatch.delenv("OPS_API_TOKEN_FILE", raising=False)
    sys.modules.pop("ops.ops_api", None)
    sys.modules.pop("ops.ui_api", None)

    ui_mod = importlib.import_module("ops.ui_api")
    with pytest.raises(RuntimeError):
        ui_mod.get_ops_token()

    ui_mod.reset_ops_token_cache()
    monkeypatch.setenv("OPS_API_TOKEN", "unit-test-token-2234567890")
    ui_mod.reset_ops_token_cache()
    assert ui_mod.get_ops_token() == "unit-test-token-2234567890"

    # Restore default for subsequent tests
    monkeypatch.setenv("OPS_API_TOKEN", "test-ops-token-1234567890")
    ui_mod.reset_ops_token_cache()
    assert ui_mod.get_ops_token() == "test-ops-token-1234567890"
