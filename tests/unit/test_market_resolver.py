from engine.core import market_resolver


def test_market_resolver_inline(monkeypatch):
    monkeypatch.setenv("MARKET_ROUTE_MAP", "BTCUSDT:margin,*:spot")
    monkeypatch.delenv("MARKET_ROUTE_MAP_FILE", raising=False)
    market_resolver._market_map.cache_clear()

    assert market_resolver.resolve_market("BTCUSDT.BINANCE", "futures") == "margin"
    assert market_resolver.resolve_market("ETHUSDT.BINANCE", "futures") == "spot"
    assert market_resolver.resolve_market("ADAUSDT", None) == "spot"


def test_market_resolver_file(tmp_path, monkeypatch):
    mapping_file = tmp_path / "routes.json"
    mapping_file.write_text('{"SOLUSDT": "margin"}', encoding="utf-8")
    monkeypatch.setenv("MARKET_ROUTE_MAP_FILE", str(mapping_file))
    monkeypatch.delenv("MARKET_ROUTE_MAP", raising=False)
    market_resolver._market_map.cache_clear()

    assert market_resolver.resolve_market("SOLUSDT.BINANCE", "spot") == "margin"
    assert market_resolver.resolve_market("XRPUSDT.BINANCE", "futures") == "futures"
