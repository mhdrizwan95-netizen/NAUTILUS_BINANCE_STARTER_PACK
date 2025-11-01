import importlib
import sys
import types

import numpy as np
import pandas as pd


def _ensure_loguru_stub():
    if "loguru" in sys.modules:
        return

    class _Logger:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    stub = types.ModuleType("loguru")
    stub.logger = _Logger()
    sys.modules["loguru"] = stub


def _ensure_pydantic_stubs():
    if "pydantic_settings" in sys.modules and "pydantic" in sys.modules:
        return

    class _FieldInfo:
        def __init__(self, default=None, **_kwargs):
            self.default = default

    def Field(default=None, **kwargs):  # noqa: ARG001 - signature mirrors real helper
        return _FieldInfo(default=default, **kwargs)

    class BaseSettings:
        def __init__(self, **overrides):
            for name, value in self.__class__.__dict__.items():
                if name.startswith("_") or name == "Config":
                    continue
                if not name.isupper():
                    continue
                default = value.default if isinstance(value, _FieldInfo) else value
                setattr(self, name, overrides.get(name, default))

    if "pydantic_settings" not in sys.modules:
        stub_settings = types.ModuleType("pydantic_settings")
        stub_settings.BaseSettings = BaseSettings
        sys.modules["pydantic_settings"] = stub_settings

    if "pydantic" not in sys.modules:
        stub_pydantic = types.ModuleType("pydantic")
        stub_pydantic.Field = Field
        sys.modules["pydantic"] = stub_pydantic
    else:
        setattr(sys.modules["pydantic"], "Field", Field)


def _ensure_manifest_stub():
    if "common.manifest" in sys.modules:
        return

    manifest_module = types.ModuleType("common.manifest")
    manifest_module.claim_unprocessed = lambda *args, **kwargs: []
    manifest_module.mark_processed = lambda *args, **kwargs: None
    manifest_module.requeue = lambda *args, **kwargs: None

    common_pkg = types.ModuleType("common")
    common_pkg.manifest = manifest_module

    sys.modules["common.manifest"] = manifest_module
    sys.modules["common"] = common_pkg


def test_train_once_respects_seed_and_metadata(monkeypatch, tmp_path):
    _ensure_loguru_stub()
    _ensure_pydantic_stubs()
    _ensure_manifest_stub()
    trainer = importlib.import_module("services.ml_service.app.trainer")

    monkeypatch.setattr(trainer.settings, "TRAIN_MIN_POINTS", 5, raising=False)
    monkeypatch.setattr(trainer.settings, "AUTO_PROMOTE", False, raising=False)
    monkeypatch.setattr(trainer.settings, "DELETE_AFTER_PROCESS", False, raising=False)
    monkeypatch.setattr(trainer.settings, "EXACTLY_ONCE", True, raising=False)
    monkeypatch.setattr(trainer.settings, "TRAIN_SEED", 1337, raising=False)

    timestamps = pd.date_range("2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(
        {
            "timestamp": (timestamps.astype("int64") // 1_000_000),
            "close": np.linspace(100.0, 109.0, num=10),
        }
    )

    claimed_ids = ["file-1"]
    monkeypatch.setattr(
        trainer,
        "_load_new_data",
        lambda: (df.copy(), claimed_ids.copy()),
    )
    monkeypatch.setattr(trainer, "_mark_claimed_as_processed", lambda *args, **kwargs: None)
    monkeypatch.setattr(trainer, "_requeue_claims", lambda *_: None)

    captured = {}

    def fake_train(X, n_states, seed):
        captured["seed"] = seed
        meta = {
            "metric_value": 1.23,
            "n_obs": int(X.shape[0]),
            "n_states": n_states,
        }
        return object(), object(), meta

    monkeypatch.setattr(trainer, "_train_hmm", fake_train)

    def fake_save_version(model, scaler, metadata):
        captured["metadata_written"] = metadata
        version_dir = tmp_path / "2024-01-01T00-00-00Z__hmm4"
        version_dir.mkdir()
        return version_dir

    monkeypatch.setattr(trainer.model_store, "save_version", fake_save_version)
    monkeypatch.setattr(trainer.model_store, "load_current", lambda: (None, None, {}))
    monkeypatch.setattr(trainer.model_store, "promote", lambda *_: None)
    monkeypatch.setattr(trainer.model_store, "prune_keep_last", lambda *_: None)

    result = trainer.train_once(n_states=4, tag="unit-test", promote=False)

    assert captured["seed"] == 1337
    assert captured["metadata_written"]["train_seed"] == 1337
    assert result["metadata"]["train_seed"] == 1337
    assert result["metadata"]["claimed_files"] == 1
