"""Ensure canonical HMM strategy modules remain importable.

These smoke tests fail fast if the modules are renamed or moved without
updating their public entry points.
"""

import importlib


def test_import_policy_hmm_module():
    module = importlib.import_module("engine.strategies.policy_hmm")
    assert module is not None


def test_import_ensemble_policy_module():
    module = importlib.import_module("engine.strategies.ensemble_policy")
    assert module is not None
