from __future__ import annotations
from typing import Dict, List
import time
import httpx

from .config import load_risk_config, norm_symbol, get_settings

_RCFG = load_risk_config()
_UNIVERSE_CACHE: dict[str, object] = {"ts": 0.0, "symbols": []}
_UNIVERSE_CACHE_TTL = 300.0  # seconds
_DEFAULT_UNIVERSE = [norm_symbol(s) for s in ("BTCUSDT", "ETHUSDT", "BNBUSDT")]


def _fetch_binance_universe() -> List[str]:
    """Pull exchangeInfo from the active Binance base (spot or futures)."""
    settings = get_settings()
    if getattr(settings, "venue", "BINANCE").upper() != "BINANCE":
        return _DEFAULT_UNIVERSE

    base = settings.futures_base if getattr(settings, "is_futures", False) else settings.spot_base or settings.base_url
    endpoint = "/fapi/v1/exchangeInfo" if getattr(settings, "is_futures", False) else "/api/v3/exchangeInfo"
    url = f"{base.rstrip('/')}{endpoint}"
    headers = {"X-MBX-APIKEY": settings.api_key} if getattr(settings, "api_key", "") else None
    response = httpx.get(url, timeout=10.0, headers=headers)
    response.raise_for_status()

    payload = response.json()
    symbols = []
    for symbol_info in payload.get("symbols", []):
        status = symbol_info.get("status")
        symbol = symbol_info.get("symbol", "")
        if status != "TRADING" or not symbol or not symbol.endswith("USDT"):
            continue
        symbols.append(norm_symbol(symbol))
    return sorted(set(symbols)) or _DEFAULT_UNIVERSE


def _dynamic_universe() -> List[str]:
    """Return cached exchange universe with a small TTL to avoid hammering REST."""
    now = time.time()
    cached = _UNIVERSE_CACHE.get("symbols") or []
    ts = float(_UNIVERSE_CACHE.get("ts") or 0.0)
    if cached and now - ts < _UNIVERSE_CACHE_TTL:
        return list(cached)

    try:
        symbols = _fetch_binance_universe()
    except Exception:
        symbols = _DEFAULT_UNIVERSE

    _UNIVERSE_CACHE["symbols"] = symbols
    _UNIVERSE_CACHE["ts"] = now
    return list(symbols)


def configured_universe() -> List[str]:
    """Universe as BASEQUOTE (no venue suffix)."""
    if _RCFG.trade_symbols:
        return [norm_symbol(s) for s in _RCFG.trade_symbols]
    return _dynamic_universe()

async def last_prices() -> Dict[str, float]:
    """Fetch last prices for all configured symbols (router's exchange client)."""
    from .app import _price_map  # Global mark price map for bulk fetch
    out: Dict[str, float] = {}
    for s in configured_universe():
        symbol = s.replace("USDT", "")
        if symbol in _price_map:
            raw = _price_map[symbol]
            if isinstance(raw, dict):
                out[s] = float(raw.get("markPrice", 0.0) or 0.0)
            else:
                out[s] = float(raw or 0.0)
            continue
        # Fallback to per-symbol fetch
        try:
            from .app import router as order_router
            out[s] = await order_router.get_last_price(f"{s}.BINANCE")
        except Exception:
            # best-effort; leave missing if not available
            continue
    return out
