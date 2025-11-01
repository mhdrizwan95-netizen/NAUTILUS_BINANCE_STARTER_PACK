import importlib, os
from fastapi.testclient import TestClient


def mk_client(env=None):
    if env:
        os.environ.update(env)
    from engine import app as appmod

    importlib.reload(appmod)
    return TestClient(appmod.app)


def test_universe_endpoint_defaults_to_trade_symbols(monkeypatch):
    c = mk_client({"TRADE_SYMBOLS": "BTCUSDT,ETHUSDT,BNBUSDT"})
    r = c.get("/universe")
    assert r.status_code == 200
    ss = r.json()["symbols"]
    assert "BTCUSDT" in ss and "ETHUSDT" in ss and "BNBUSDT" in ss


def test_prices_endpoint_shape(monkeypatch):
    c = mk_client({"TRADE_SYMBOLS": "BTCUSDT"})
    # Stub price
    from engine import app as appmod

    appmod.order_router.exchange_client().ticker_price = lambda sym: 50000.0
    r = c.get("/prices")
    assert r.status_code == 200
    assert r.json()["prices"].get("BTCUSDT") == 50000.0


def test_portfolio_marks_dust(monkeypatch):
    c = mk_client({"TRADE_SYMBOLS": "BTCUSDT", "DUST_THRESHOLD_USD": "2"})
    from engine import app as appmod

    # Snapshot shim
    appmod.order_router.portfolio_snapshot = lambda: {
        "equity_usd": 100.0,
        "cash_usd": 98.0,
        "pnl": {"realized": 0, "unrealized": 0},
        "positions": [
            {
                "symbol": "BTCUSDT.BINANCE",
                "qty_base": 0.00001,
                "avg_price_quote": 50000.0,
            }
        ],
    }
    appmod.order_router.exchange_client().ticker_price = lambda sym: 50000.0
    r = c.get("/portfolio")
    assert r.status_code == 200
    pos = r.json()["positions"][0]
    assert pos["is_dust"] is True
