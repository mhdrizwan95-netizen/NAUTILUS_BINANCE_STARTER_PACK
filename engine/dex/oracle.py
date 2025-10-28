from __future__ import annotations

"""
Price oracle helpers for the DEX sniper.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional

import httpx


DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{token}"


@dataclass(slots=True)
class PriceEntry:
    price: float
    updated: float


class DexPriceOracle:
    def __init__(self, *, transport: str = "dexscreener", ttl: float = 10.0) -> None:
        self.transport = transport
        self.ttl = ttl
        self._cache: Dict[str, PriceEntry] = {}
        self._client = httpx.AsyncClient(timeout=10.0)
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def price_usd(self, token_identifier: str) -> Optional[float]:
        now = time.time()
        entry = self._cache.get(token_identifier)
        if entry and (now - entry.updated) < self.ttl:
            return entry.price
        if self.transport == "dexscreener":
            price = await self._dexscreener_price(token_identifier)
        else:
            raise ValueError(f"Unsupported price oracle transport: {self.transport}")
        if price is not None:
            self._cache[token_identifier] = PriceEntry(price=price, updated=now)
        return price

    async def _dexscreener_price(self, token_identifier: str) -> Optional[float]:
        url = DEXSCREENER_TOKEN_URL.format(token=token_identifier)
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json() or {}
        pairs = data.get("pairs") or []
        for pair in pairs:
            price = pair.get("priceUsd")
            if price:
                try:
                    return float(price)
                except (TypeError, ValueError):
                    continue
        return None
