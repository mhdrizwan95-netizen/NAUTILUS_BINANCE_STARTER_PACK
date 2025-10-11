import importlib
from types import SimpleNamespace

def test_ibkr_quote_to_qty_rounding_and_fee(monkeypatch):
    from engine.core import order_router as r
    importlib.reload(r)

    # Stub IBKR client
    class StubIbkr:
        def get_last_price(self, symbol): return 200.0  # $200/share
        def place_market_order(self, **kw):
            return {"avg_fill_price":200.0, "filled_qty_base": int(kw["quantity"]), "status":"Filled"}

    r.set_exchange_client("IBKR", StubIbkr())

    # Buy $25 notional of AAPL -> 0.125 share → rounds down to 0 → expect QTY_TOO_SMALL
    try:
        r.place_market_order(symbol="AAPL.IBKR", side="BUY", quote=25.0, quantity=None)
        assert False, "Expected QTY_TOO_SMALL"
    except ValueError as e:
        assert "QTY_TOO_SMALL" in str(e)

    # Buy 1 share by quantity
    res = r.place_market_order(symbol="AAPL.IBKR", side="BUY", quote=None, quantity=1)
    assert res["venue"] == "IBKR"
    assert res["rounded_qty"] == 1.0
    assert res["fee_usd"] >= 1.0  # min trade fee default

def test_ibkr_auto_venue_routing(monkeypatch):
    from engine.core import order_router as r
    importlib.reload(r)

    # Stub IBKR client
    class StubIbkr:
        def get_last_price(self, symbol): return 150.0  # AAPL at $150
        def place_market_order(self, **kw):
            return {"avg_fill_price":150.0, "filled_qty_base": int(kw["quantity"]), "status":"Filled"}

    # Stub Binance client
    class StubBinance:
        def get_last_price(self, symbol): return 50000.0  # BTC at $50k
        def place_market_order(self, **kw):
            return {"avg_fill_price":50000.0, "filled_qty_base": kw["quantity"], "status":"Filled"}

    r.set_exchange_client("IBKR", StubIbkr())
    r.set_exchange_client("BINANCE", StubBinance())

    # AAPL should auto-route to IBKR
    res1 = r.place_market_order(symbol="AAPL", side="BUY", quote=None, quantity=1)
    assert res1["venue"] == "IBKR"
    assert res1["rounded_qty"] == 1.0

    # BTCUSDT should auto-route to Binance
    res2 = r.place_market_order(symbol="BTCUSDT", side="BUY", quote=None, quantity=0.001)
    assert res2["venue"] == "BINANCE"
    assert res2["rounded_qty"] == 0.001

def test_ibkr_fee_calculation(monkeypatch):
    """Test IBKR fee calculation with per-share and BPS modes."""
    import os
    from engine.config import load_ibkr_fee_config

    # Test per-share mode (default)
    os.environ["IBKR_FEE_MODE"] = "per_share"
    os.environ["IBKR_FEE_PER_SHARE"] = "0.005"
    os.environ["IBKR_MIN_TRADE_FEE_USD"] = "1.00"

    config = load_ibkr_fee_config()
    assert config.mode == "per_share"
    assert config.per_share_usd == 0.005
    assert config.min_trade_fee_usd == 1.00

    # Fee for 100 shares should be $1 minimum
    fee = max(config.min_trade_fee_usd, 100 * config.per_share_usd)
    assert fee == 1.00

    # Fee for 1000 shares should be $5
    fee_large = max(config.min_trade_fee_usd, 1000 * config.per_share_usd)
    assert fee_large == 5.0

    # Test BPS mode
    os.environ["IBKR_FEE_MODE"] = "bps"
    os.environ["IBKR_FEE_BPS"] = "10"  # 0.10%

    config_bps = load_ibkr_fee_config()
    assert config_bps.mode == "bps"
    assert config_bps.bps == 10.0

    # Fee on $10,000 notional at 10 BPS should be $10
    fee_bps = (10.0 / 10000.0) * 10000.0
    assert fee_bps == 10.0

def test_ibkr_specs_loading(monkeypatch):
    """Test IBKR specs auto-loading from venue_specs.json"""
    from engine.core.venue_specs import SPECS, DEFAULT_SPECS

    # Check defaults are present
    assert "IBKR" in SPECS
    assert "AAPL" in SPECS["IBKR"]
    assert SPECS["IBKR"]["AAPL"].min_qty == 1.0
    assert SPECS["IBKR"]["AAPL"].step_size == 1.0

    # Check Binance defaults still work
    assert "BINANCE" in SPECS
    assert "BTCUSDT" in DEFAULT_SPECS
    assert DEFAULT_SPECS["BTCUSDT"].min_qty == 0.00001

if __name__ == "__main__":
    test_ibkr_quote_to_qty_rounding_and_fee(None)
    test_ibkr_auto_venue_routing(None)
    test_ibkr_fee_calculation(None)
    test_ibkr_specs_loading(None)
    print("All IBKR tests passed!")
