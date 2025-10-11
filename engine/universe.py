from __future__ import annotations
from typing import Dict, List
import time, asyncio
from .config import load_risk_config, norm_symbol

_RCFG = load_risk_config()

def configured_universe() -> List[str]:
    """Universe as BASEQUOTE (no venue suffix)."""
    if _RCFG.trade_symbols:
        return [norm_symbol(s) for s in _RCFG.trade_symbols]
    # Since TRADE_SYMBOLS should always be set, no fallback needed
    return []

async def last_prices() -> Dict[str, float]:
    """Fetch last prices for all configured symbols (router's exchange client)."""
    from .app import router as order_router  # import here to avoid circular import
    out: Dict[str, float] = {}
    for s in configured_universe():
        try:
            out[s] = await order_router.get_last_price(f"{s}.BINANCE")
        except Exception:
            # best-effort; leave missing if not available
            continue
    return out
