"""Utilities for publishing normalized external events onto the engine bus."""

from __future__ import annotations

import logging
import time
from typing import Iterable, List, Sequence

from engine.core.signal_queue import SIGNAL_QUEUE, QueuedEvent
from engine.events.schemas import ExternalEvent
from engine import metrics

_LOG = logging.getLogger("engine.events.publisher")

_DEFAULT_PRIORITY = 0.5


def _normalize_hints(candidates: Iterable[str]) -> List[str]:
    hints: List[str] = []
    for item in candidates:
        if not item:
            continue
        text = str(item).strip()
        if not text:
            continue
        hints.append(text.upper())
    # Remove duplicates while preserving order
    seen = set()
    deduped: List[str] = []
    for hint in hints:
        if hint in seen:
            continue
        seen.add(hint)
        deduped.append(hint)
    return deduped


def _derive_hints(event: ExternalEvent) -> List[str]:
    payload = event.payload or {}
    candidates: List[str] = []
    for key in ("asset_hints", "symbols", "symbol", "tickers", "pairs", "pair"):
        value = payload.get(key)
        if isinstance(value, (list, tuple, set)):
            candidates.extend(value)
        elif value:
            candidates.append(value)
    meta_hints = event.meta.get("asset_hints") if isinstance(event.meta, dict) else None
    if meta_hints:
        if isinstance(meta_hints, (list, tuple, set)):
            candidates.extend(meta_hints)
        else:
            candidates.append(meta_hints)
    return _normalize_hints(candidates)


def _resolve_priority(event: ExternalEvent, priority: float | None) -> float:
    if priority is not None:
        return float(priority)
    meta_priority = None
    if isinstance(event.meta, dict):
        meta_priority = event.meta.get("priority")
    if meta_priority is not None:
        try:
            return float(meta_priority)
        except (TypeError, ValueError):
            pass
    return _DEFAULT_PRIORITY


def _resolve_expiry(event: ExternalEvent, expires_at: float | None) -> float | None:
    if expires_at is not None:
        return float(expires_at)
    if isinstance(event.meta, dict):
        if "expires_at" in event.meta:
            try:
                return float(event.meta["expires_at"])
            except (TypeError, ValueError):
                pass
        ttl = event.meta.get("ttl_sec")
        if ttl is not None:
            try:
                return time.time() + float(ttl)
            except (TypeError, ValueError):
                pass
    return None


async def publish_external_event(
    event: ExternalEvent,
    *,
    priority: float | None = None,
    expires_at: float | None = None,
    asset_hints: Sequence[str] | None = None,
) -> str:
    """Enqueue an :class:`ExternalEvent` for fan-out on ``events.external_feed``.

    Returns the event id used for downstream dedupe.
    """

    normalized = event.with_default_id()
    resolved_priority = _resolve_priority(normalized, priority)
    resolved_expiry = _resolve_expiry(normalized, expires_at)
    hints = _normalize_hints(asset_hints or []) if asset_hints else _derive_hints(normalized)

    data = normalized.model_dump(mode="json")
    data["asset_hints"] = hints
    data["priority"] = resolved_priority

    await SIGNAL_QUEUE.put(
        QueuedEvent(
            topic="events.external_feed",
            data=data,
            priority=resolved_priority,
            expires_at=resolved_expiry,
            source=normalized.source,
        )
    )

    metrics.external_feed_events_total.labels(normalized.source).inc()
    metrics.events_external_feed_published_total.labels(source=normalized.source).inc()
    metrics.external_feed_last_event_epoch.labels(normalized.source).set(time.time())

    _LOG.debug("Queued external event %s from %s", normalized.id, normalized.source)
    return normalized.id
