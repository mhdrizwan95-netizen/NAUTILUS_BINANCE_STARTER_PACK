from __future__ import annotations

"""
Dexscreener lightweight client + loop.

This module provides a minimal fetcher for trending pairs from Dexscreener
and a loop that evaluates heuristic filters to produce Tier A/B candidates
as per the playbook. It publishes events on the global BUS when enabled.

By default, this module is inert unless DEX_FEED_ENABLED=true.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


DEX_API = os.getenv("DEXSCREENER_API", "https://api.dexscreener.com/latest/dex/tokens")


@dataclass
class DexCandidate:
    chain: str
    addr: str
    symbol: str
    name: str
    price_usd: float
    liquidity_usd: float
    mcap_usd: float
    vol_1h: float
    vol_24h: float
    change_5m: float
    holders: int | None = None
    tier: str = "B"


def _as_float(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _tier_for(item: Dict[str, Any]) -> Optional[DexCandidate]:
    # Extract required fields with defaults
    chain = str(item.get("chainId") or item.get("chain") or "?")
    addr = str(item.get("address") or item.get("pairAddress") or item.get("id") or "")
    base = (item.get("baseToken") or {})
    symbol = str(base.get("symbol") or item.get("symbol") or "?")
    name = str(base.get("name") or item.get("name") or symbol)
    price = _as_float(item.get("priceUsd") or item.get("price"))
    liq = _as_float(item.get("liquidity", {}).get("usd") if isinstance(item.get("liquidity"), dict) else item.get("liquidity"))
    mcap = _as_float(item.get("fdv") or item.get("mcap") or 0.0)
    vol1h = _as_float(item.get("volume", {}).get("h1") if isinstance(item.get("volume"), dict) else item.get("volumeH1"))
    vol24 = _as_float(item.get("volume", {}).get("h24") if isinstance(item.get("volume"), dict) else item.get("volumeH24"))
    chg5 = _as_float(item.get("priceChange", {}).get("m5") if isinstance(item.get("priceChange"), dict) else item.get("change5m"))

    if (mcap < 3_000_000) or (mcap > 50_000_000):
        return None
    if liq < 200_000:
        return None
    # 1h volume delta heuristic: vol1h relative to prior hours; approximate using vol1h/avg(24h/24)
    avg1h = (vol24 / 24.0) if vol24 and vol24 > 0 else 0.0
    if avg1h <= 0 or (vol1h / max(avg1h, 1e-9)) < 3.0:
        return None

    tier = "B"
    # A more complete implementation would check social surge; placeholder keeps Tier B
    return DexCandidate(
        chain=chain,
        addr=addr,
        symbol=symbol,
        name=name,
        price_usd=price,
        liquidity_usd=liq,
        mcap_usd=mcap,
        vol_1h=vol1h,
        vol_24h=vol24,
        change_5m=chg5,
        holders=None,
        tier=tier,
    )


async def fetch_top_gainers(chains: list[str] | None = None) -> List[DexCandidate]:
    chains = chains or ["bsc", "eth", "base"]
    params = {"chains": ",".join(chains)}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get("https://api.dexscreener.com/latest/dex/search?q=trending", params=params)
            r.raise_for_status()
            js = r.json() or {}
            pairs = js.get("pairs") or []
            out: List[DexCandidate] = []
            for item in pairs:
                c = _tier_for(item)
                if c:
                    out.append(c)
            return out
        except Exception:
            return []


async def dexscreener_loop(poll_sec: float = 10.0) -> None:
    if os.getenv("DEX_FEED_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return
    from engine.core.event_bus import publish_strategy_event
    # Optional social ROC tiering
    try:
        from engine.feeds.social import roc as social_roc
    except Exception:
        social_roc = lambda _: 0.0
    while True:
        try:
            cands = await fetch_top_gainers()
            for c in cands[:5]:
                tier = "A" if social_roc(c.symbol) >= 2.5 else c.tier
                await publish_strategy_event("dex_candidate", {
                    "symbol": c.symbol,
                    "chain": c.chain,
                    "addr": c.addr,
                    "tier": tier,
                    "mcap": c.mcap_usd,
                    "liq": c.liquidity_usd,
                    "vol1h": c.vol_1h,
                    "chg5m": c.change_5m,
                })
        except Exception:
            pass
        await asyncio.sleep(poll_sec)
