import os, json, importlib, shutil
from pathlib import Path
from fastapi.testclient import TestClient

def test_atomic_snapshot_and_load(tmp_path, monkeypatch):
    # Redirect state dir
    sd = tmp_path / "state"
    monkeypatch.setattr("engine.state.STATE_DIR", sd)
    snap_path = sd / "portfolio.json"
    monkeypatch.setattr("engine.state.SNAP_PATH", snap_path)
    sd.mkdir(parents=True, exist_ok=True)
    store = __import__('engine.state', fromlist=['SnapshotStore']).SnapshotStore(snap_path)
    snap = {"equity_usd": 100.0, "cash_usd": 99.0, "positions": [], "pnl":{"realized":0,"unrealized":0}}
    store.save(snap)
    loaded = store.load()
    assert loaded["equity_usd"] == 100.0
    assert "ts_ms" in loaded

def test_portfolio_endpoint_falls_back_to_snapshot(tmp_path, monkeypatch):
    # force snapshot presence and router failure
    import engine.state as st
    sd = tmp_path / "state"
    monkeypatch.setattr("engine.state.STATE_DIR", sd)
    snap_path = sd / "portfolio.json"
    monkeypatch.setattr("engine.state.SNAP_PATH", snap_path)
    sd.mkdir(parents=True, exist_ok=True)
    store = st.SnapshotStore(snap_path)
    store.save({"equity_usd": 123.0, "cash_usd": 120.0, "positions": [], "pnl":{"realized":0,"unrealized":0}})
    import engine.app as appmod
    importlib.reload(appmod)
    c = TestClient(appmod.app)
    r = c.get("/portfolio")
    assert r.status_code == 200
    assert r.json()["equity_usd"] == 123.0

def test_state_basic_imports():
    from engine.state import SnapshotStore
    from engine.reconcile import reconcile_since_snapshot
    assert SnapshotStore is not None
    assert reconcile_since_snapshot is not None
