import os

def engine_endpoints() -> list[str]:
    """Return list of engine API URLs."""
    urls = os.getenv("ENGINE_ENDPOINTS", "http://engine_binance:8000").split(",")
    return [u.strip() for u in urls if u.strip()]
