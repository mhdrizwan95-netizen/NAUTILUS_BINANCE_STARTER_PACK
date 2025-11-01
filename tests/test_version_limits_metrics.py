import importlib
import os
from fastapi.testclient import TestClient


def mk_client(env=None):
    if env:
        os.environ.update(env)
    from engine import app as appmod

    importlib.reload(appmod)
    return TestClient(appmod.app)


def test_version_and_limits(monkeypatch):
    os.environ["GIT_SHA"] = "abc123"
    os.environ["MODEL_TAG"] = "hmm_v1"
    os.environ["EXPOSURE_CAP_SYMBOL_USD"] = "123"
    c = mk_client()
    v = c.get("/version").json()
    assert v["git_sha"] == "abc123"
    assert v["model_tag"] == "hmm_v1"
    l = c.get("/limits").json()
    assert l["exposure_cap_symbol_usd"] == 123.0


def test_reconcile_lag_gauge(monkeypatch):
    c = mk_client()
    # health before reconcile should have lag present or None
    h1 = c.get("/health").json()
    # simulate a reconcile completion by calling /health again after setting internal ts (if exposed),
    # otherwise just assert field exists
    assert "reconcile_lag_seconds" in h1
