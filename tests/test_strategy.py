import importlib
import os

from fastapi.testclient import TestClient

AUTH_HEADERS = {"X-Ops-Token": os.environ["OPS_API_TOKEN"]}


def mk_client():
    from engine import app as appmod

    importlib.reload(appmod)
    # Clear strategy globals for clean tests
    from engine import strategy as strat

    strat._loop_thread = None
    strat._stop_flag.clear()
    strat._mac.__init__(9, 21)  # Reset MA cross
    return TestClient(appmod.app)


def test_strategy_signal_dry_run():
    os.makedirs("engine/logs", exist_ok=True)
    c = mk_client()
    r = c.post(
        "/strategy/signal",
        headers=AUTH_HEADERS,
        json={"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 10, "tag": "test"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "simulated"
    assert j["symbol"] == "BTCUSDT.BINANCE"


def test_strategy_signal_respects_rails():
    os.makedirs("engine/logs", exist_ok=True)
    c = mk_client()
    r = c.post(
        "/strategy/signal",
        headers=AUTH_HEADERS,
        json={"symbol": "DOGEUSDT.BINANCE", "side": "BUY", "quote": 10},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["error"] == "SYMBOL_NOT_ALLOWED"


def test_strategy_signal_override_dry_run():
    os.makedirs("engine/logs", exist_ok=True)
    c = mk_client()
    r = c.post(
        "/strategy/signal",
        headers=AUTH_HEADERS,
        json={"symbol": "BTCUSDT.BINANCE", "side": "BUY", "quote": 10, "dry_run": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "simulated"
