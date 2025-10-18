from __future__ import annotations
from typing import Dict, List
import time, asyncio
from .config import load_risk_config, norm_symbol, list_all_testnet_pairs

_RCFG = load_risk_config()

def configured_universe() -> List[str]:
    """Universe as BASEQUOTE (no venue suffix)."""
    if _RCFG.trade_symbols:
        return [norm_symbol(s) for s in _RCFG.trade_symbols]

    # Dynamic loading: when TRADE_SYMBOLS=* or ALL, fetch all testnet pairs
    try:
        # Get current event loop to check if running
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't await, use synchronous fallback in universe.py context
            # For now, return common pairs; we'll need to modify app startup
            import httpx
            url = "https://testnet.binance.vision/api/v3/exchangeInfo"
            response = httpx.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                symbols = []
                for symbol_info in data.get("symbols", []):
                    if symbol_info.get("status") == "TRADING":
                        symbol = symbol_info.get("symbol", "")
                        if symbol.endswith("USDT"):
                            symbols.append(norm_symbol(symbol))
                return sorted(symbols)
    except Exception:
        pass

    # Fallback
    return [norm_symbol(s) for s in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]]

async def last_prices() -> Dict[str, float]:
    """Fetch last prices for all configured symbols (router's exchange client)."""
    from .app import _price_map  # Global mark price map for bulk fetch
    out: Dict[str, float] = {}
    for s in configured_universe():
        symbol = s.replace("USDT", "")
        if symbol in _price_map:
            out[s] = _price_map[symbol]
            continue
        # Fallback to per-symbol fetch
        try:
            from .app import router as order_router
            out[s] = await order_router.get_last_price(f"{s}.BINANCE")
        except Exception:
            # best-effort; leave missing if not available
            continue
    return out
