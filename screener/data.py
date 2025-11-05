from shared.binance_http import fetch_json


def klines_1m(sym: str, n: int = 60):
    return fetch_json(
        "/api/v3/klines",
        params={"symbol": sym, "interval": "1m", "limit": n},
    )


def orderbook(sym: str, limit: int = 10):
    return fetch_json(
        "/api/v3/depth",
        params={"symbol": sym, "limit": limit},
    )
