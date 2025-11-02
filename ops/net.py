"""Shared network client utilities (timeouts, retries) for ops services."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Iterable, Optional

import httpx

DEFAULT_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=4)
DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=6.0, write=6.0, pool=6.0)


def create_async_client(
    *,
    limits: httpx.Limits | None = None,
    timeout: httpx.Timeout | None = None,
    trust_env: bool = True,
    headers: Optional[dict[str, str]] = None,
) -> httpx.AsyncClient:
    """Factory for AsyncClient with shared limits and timeout defaults."""
    return httpx.AsyncClient(
        limits=limits or DEFAULT_LIMITS,
        timeout=timeout or DEFAULT_TIMEOUT,
        trust_env=trust_env,
        headers=headers,
    )


def create_client(
    *,
    limits: httpx.Limits | None = None,
    timeout: httpx.Timeout | None = None,
    trust_env: bool = True,
    headers: Optional[dict[str, str]] = None,
) -> httpx.Client:
    """Factory for synchronous Clients with shared defaults."""
    return httpx.Client(
        limits=limits or DEFAULT_LIMITS,
        timeout=timeout or DEFAULT_TIMEOUT,
        trust_env=trust_env,
        headers=headers,
    )


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff_base: float = 0.5,
    backoff_factor: float = 2.0,
    backoff_cap: float = 8.0,
    retry_statuses: Iterable[int] = (500, 502, 503, 504),
    **kwargs: Any,
) -> httpx.Response:
    """
    Execute an HTTP request with capped exponential backoff.

    Retries on network errors and the supplied status codes.
    """
    attempt = 0
    last_exc: Exception | None = None
    while True:
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code not in retry_statuses:
                return response
        except httpx.RequestError as exc:
            last_exc = exc
        else:
            last_exc = None

        attempt += 1
        if attempt > retries:
            if last_exc:
                raise last_exc
            response.raise_for_status()
            return response

        delay = min(backoff_base * (backoff_factor ** (attempt - 1)), backoff_cap)
        jitter = random.uniform(0, 0.5)
        await asyncio.sleep(delay + jitter)


def request_with_retry_sync(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff_base: float = 0.5,
    backoff_factor: float = 2.0,
    backoff_cap: float = 8.0,
    retry_statuses: Iterable[int] = (500, 502, 503, 504),
    **kwargs: Any,
) -> httpx.Response:
    """Synchronous variant of request_with_retry."""
    attempt = 0
    last_exc: Exception | None = None
    while True:
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in retry_statuses:
                return response
        except httpx.RequestError as exc:
            last_exc = exc
        else:
            last_exc = None

        attempt += 1
        if attempt > retries:
            if last_exc:
                raise last_exc
            response.raise_for_status()
            return response

        delay = min(backoff_base * (backoff_factor ** (attempt - 1)), backoff_cap)
        jitter = random.uniform(0, 0.5)
        time.sleep(delay + jitter)


__all__ = [
    "create_async_client",
    "create_client",
    "request_with_retry",
    "request_with_retry_sync",
]
