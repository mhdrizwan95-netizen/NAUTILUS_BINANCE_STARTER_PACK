from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from typing import Any, Protocol

from fastapi import HTTPException, status

from ops.prometheus import get_or_create_counter

logger = logging.getLogger(__name__)

_CACHE_MAX = 512
_DEFAULT_REDIS_TTL = 60 * 60 * 24
_DEFAULT_CLAIM_TTL = 300
_REPLAY_COUNTER = get_or_create_counter(
    "idempotency_replays_total", "Number of responses served from idempotency cache"
)
_PENDING_COUNTER = get_or_create_counter(
    "idempotency_pending_total", "Number of requests blocked due to an in-flight reservation"
)
_NEW_COUNTER = get_or_create_counter(
    "idempotency_new_total", "Number of fresh idempotent requests accepted for execution"
)


class IdempotencyStore(Protocol):
    def get(self, key: str) -> tuple[float, dict[str, Any]] | None: ...

    def set(self, key: str, value: tuple[float, dict[str, Any]]) -> None: ...


class ClaimStore(Protocol):
    def claim(self, key: str, ttl_seconds: int) -> bool: ...

    def release(self, key: str) -> None: ...


class MemoryStore(IdempotencyStore):
    def __init__(self, capacity: int = _CACHE_MAX) -> None:
        self._capacity = capacity
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> tuple[float, dict[str, Any]] | None:
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, value: tuple[float, dict[str, Any]]) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)


class MemoryClaimStore(ClaimStore):
    def __init__(self) -> None:
        self._claims: dict[str, float] = {}
        self._lock = RLock()

    def claim(self, key: str, ttl_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            expiry = self._claims.get(key)
            if expiry and expiry > now:
                return False
            self._claims[key] = now + ttl_seconds
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._claims.pop(key, None)

    def _purge_expired(self, now: float) -> None:
        expired = [claim for claim, expiry in self._claims.items() if expiry <= now]
        for claim in expired:
            self._claims.pop(claim, None)


class RedisStore(IdempotencyStore):
    def __init__(
        self,
        client: Any,
        *,
        ttl_seconds: int,
        fallback: IdempotencyStore,
        error_types: tuple[type[BaseException], ...],
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._fallback = fallback
        self._error_types = error_types

    def get(self, key: str) -> tuple[float, dict[str, Any]] | None:
        try:
            raw = self._client.get(key)
        except self._error_types as exc:  # pragma: no cover - network errors
            logger.warning("idempotency.redis_get_failed", extra={"error": str(exc)})
            return self._fallback.get(key)
        if raw is None:
            return self._fallback.get(key)
        try:
            payload = json.loads(raw)
            return float(payload["ts"]), payload["response"]
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("idempotency.redis_payload_invalid", extra={"error": str(exc)})
            return None

    def set(self, key: str, value: tuple[float, dict[str, Any]]) -> None:
        ts, response = value
        try:
            body = json.dumps({"ts": ts, "response": response}, default=str)
            self._client.set(key, body, ex=self._ttl_seconds)
        except self._error_types as exc:  # pragma: no cover - network errors
            logger.warning("idempotency.redis_set_failed", extra={"error": str(exc)})
            self._fallback.set(key, value)


class RedisClaimStore(ClaimStore):
    def __init__(
        self,
        client: Any,
        *,
        fallback: ClaimStore,
        error_types: tuple[type[BaseException], ...],
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._error_types = error_types

    def _claim_key(self, key: str) -> str:
        return f"idempotency:claim:{key}"

    def claim(self, key: str, ttl_seconds: int) -> bool:
        claim_key = self._claim_key(key)
        try:
            return bool(self._client.set(claim_key, "1", ex=ttl_seconds, nx=True))
        except self._error_types as exc:  # pragma: no cover - network errors
            logger.warning("idempotency.redis_claim_failed", extra={"error": str(exc)})
            return self._fallback.claim(key, ttl_seconds)

    def release(self, key: str) -> None:
        claim_key = self._claim_key(key)
        try:
            self._client.delete(claim_key)
        except self._error_types as exc:  # pragma: no cover - network errors
            logger.warning("idempotency.redis_release_failed", extra={"error": str(exc)})
            self._fallback.release(key)


def _build_store() -> IdempotencyStore:
    redis_url = os.getenv("IDEMPOTENCY_REDIS_URL")
    ttl_seconds = int(os.getenv("IDEMPOTENCY_REDIS_TTL_SECONDS", str(_DEFAULT_REDIS_TTL)))
    memory_store = MemoryStore()
    if not redis_url:
        logger.info("idempotency.store", extra={"backend": "memory"})
        return memory_store
    try:  # pragma: no cover - requires redis server for full coverage
        import redis
    except ImportError as exc:  # pragma: no cover - optional dependency
        logger.warning(
            "idempotency.redis_unavailable",
            extra={"error": str(exc), "backend": "memory"},
        )
        return memory_store

    try:
        client = redis.Redis.from_url(redis_url)
        client.ping()
    except redis.exceptions.RedisError as exc:  # pragma: no cover - network errors
        logger.warning(
            "idempotency.redis_unavailable",
            extra={"error": str(exc), "backend": "memory"},
        )
        return memory_store
    except ValueError as exc:  # pragma: no cover - invalid URL
        logger.warning(
            "idempotency.redis_config_invalid",
            extra={"error": str(exc), "backend": "memory"},
        )
        return memory_store

    logger.info("idempotency.store", extra={"backend": "redis", "url": redis_url})
    return RedisStore(
        client=client,
        ttl_seconds=ttl_seconds,
        fallback=memory_store,
        error_types=(redis.exceptions.RedisError,),
    )


def _build_claim_store(memory_claim_store: ClaimStore) -> ClaimStore:
    redis_url = os.getenv("IDEMPOTENCY_REDIS_URL")
    if not redis_url:
        logger.info("idempotency.claim_store", extra={"backend": "memory"})
        return memory_claim_store
    try:  # pragma: no cover - requires redis server for full coverage
        import redis
    except ImportError as exc:  # pragma: no cover - optional dependency
        logger.warning(
            "idempotency.redis_claim_unavailable",
            extra={"error": str(exc), "backend": "memory"},
        )
        return memory_claim_store

    try:
        client = redis.Redis.from_url(redis_url)
        client.ping()
    except redis.exceptions.RedisError as exc:  # pragma: no cover - network errors
        logger.warning(
            "idempotency.redis_claim_unavailable",
            extra={"error": str(exc), "backend": "memory"},
        )
        return memory_claim_store
    except ValueError as exc:  # pragma: no cover - invalid URL
        logger.warning(
            "idempotency.redis_claim_config_invalid",
            extra={"error": str(exc), "backend": "memory"},
        )
        return memory_claim_store

    logger.info("idempotency.claim_store", extra={"backend": "redis", "url": redis_url})
    return RedisClaimStore(
        client=client,
        fallback=memory_claim_store,
        error_types=(redis.exceptions.RedisError,),
    )


_STORE = _build_store()
_MEMORY_CLAIM_STORE = MemoryClaimStore()
_CLAIM_STORE = _build_claim_store(_MEMORY_CLAIM_STORE)
_CLAIM_TTL = int(os.getenv("IDEMPOTENCY_CLAIM_TTL_SECONDS", str(_DEFAULT_CLAIM_TTL)))


def _lookup(key: str | None) -> tuple[float, dict[str, Any]] | None:
    if not key:
        return None
    return _STORE.get(key)


def _claim(key: str | None) -> bool:
    if not key:
        return True
    return _CLAIM_STORE.claim(key, _CLAIM_TTL)


def _release(key: str | None) -> None:
    if not key:
        return
    _CLAIM_STORE.release(key)


def enforce_fresh_request(key: str | None) -> None:
    """Raise if the Idempotency-Key has already been processed."""
    cached = _lookup(key)
    if cached:
        ts, payload = cached
        _REPLAY_COUNTER.inc()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "idempotency.replayed",
                "message": "A request with this Idempotency-Key already succeeded.",
                "idempotencyKey": key,
                "timestamp": ts,
                "previousResult": payload,
            },
        )

    if not _claim(key):
        _PENDING_COUNTER.inc()
        _REPLAY_COUNTER.inc()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "idempotency.pending",
                "message": "A request with this Idempotency-Key is already in flight.",
                "idempotencyKey": key,
            },
        )


@contextmanager
def reserve_idempotency(key: str | None) -> Iterator[None]:
    """Context manager guarding a request so only one in-flight mutation executes."""
    enforce_fresh_request(key)
    if key:
        _NEW_COUNTER.inc()
    try:
        yield
    except Exception:
        _release(key)
        raise


def store_response(key: str | None, response: dict[str, Any]) -> None:
    """Persist the successful response for replay detection."""
    if not key:
        return
    _STORE.set(key, (time.time(), response))
    _release(key)


def release_idempotency(key: str | None) -> None:
    """Allow callers to explicitly release reservations on failure paths."""
    _release(key)
