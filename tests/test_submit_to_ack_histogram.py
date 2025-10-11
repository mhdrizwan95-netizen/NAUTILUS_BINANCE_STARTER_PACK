import importlib
from types import SimpleNamespace
from fastapi.testclient import TestClient

def test_submit_ack_histogram(monkeypatch):
    from engine import app as appmod
    importlib.reload(appmod)
    # Patch router client so it returns fast
    appmod.order_router.exchange_client().place_market_order = lambda **kw: {"avg_fill_price":50000.0,"filled_qty_base":0.001}
    c = TestClient(appmod.app)
    r = c.post("/orders/market", json={"symbol":"BTCUSDT.BINANCE","side":"BUY","quote":10})
    assert r.status_code in (200, 400, 403)  # depending on rails config
    # Metrics present
    m = c.get("/metrics").text
    assert "submit_to_ack_ms_bucket" in m
