"""
Price oracle helpers for the DEX sniper.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{token}"  # nosec B105
_ORACLE_ERRORS: tuple[type[Exception], ...] = (
    httpx.HTTPError,
    ValueError,
    KeyError,
    RuntimeError,
)


class UnsupportedOracleTransportError(ValueError):
    """Raised when an unsupported oracle backend is requested."""

    def __init__(self, transport: str) -> None:
        super().__init__(f"Unsupported price oracle transport: {transport}")


@dataclass(slots=True)
class PriceEntry:
    price: float
    updated: float


class DexPriceOracle:
    def __init__(self, *, transport: str = "dexscreener", ttl: float = 10.0) -> None:
        self.transport = transport
        self.ttl = ttl
        self._cache: dict[str, PriceEntry] = {}
        self._client = httpx.AsyncClient(timeout=10.0)
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def price_usd(self, token_identifier: str) -> float | None:
        now = time.time()
        entry = self._cache.get(token_identifier)
        if entry and (now - entry.updated) < self.ttl:
            return entry.price
        if self.transport == "dexscreener":
            price = await self._dexscreener_price(token_identifier)
        else:
            raise UnsupportedOracleTransportError(self.transport)
        if price is not None:
            self._cache[token_identifier] = PriceEntry(price=price, updated=now)
        return price

    async def _dexscreener_price(self, token_identifier: str) -> float | None:
        url = DEXSCREENER_TOKEN_URL.format(token=token_identifier)
        # Simple retry with exponential backoff on transient failures
        last_exc = None
        for attempt in range(3):
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                data = resp.json() or {}
                break
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_exc = exc
                await asyncio.sleep(0.25 * (attempt + 1))
        else:
            raise last_exc  # propagate last error after retries

        pairs = data.get("pairs") or []
        for pair in pairs:
            price = pair.get("priceUsd")
            if price:
                try:
                    return float(price)
                except (TypeError, ValueError):
                    continue
        return None
