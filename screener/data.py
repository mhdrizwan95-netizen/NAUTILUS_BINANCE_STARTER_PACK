import httpx

BASE = "https://api.binance.com"


def klines_1m(sym: str, n: int = 60):
    return httpx.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": sym, "interval": "1m", "limit": n},
        timeout=10,
    ).json()


def orderbook(sym: str, limit: int = 10):
    return httpx.get(
        f"{BASE}/api/v3/depth", params={"symbol": sym, "limit": limit}, timeout=10
    ).json()
