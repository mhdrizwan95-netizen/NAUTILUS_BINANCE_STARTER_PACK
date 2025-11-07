"""Backwards compatibility bridge for legacy external event topics."""

from __future__ import annotations

import logging
import weakref
from typing import Any, Dict

from engine.events.publisher import publish_external_event
from engine.events.schemas import ExternalEvent

_LOG = logging.getLogger("engine.compat.events_bridge")

_BRIDGED_BUSES: "weakref.WeakSet" = weakref.WeakSet()


def init_external_feed_bridge(bus) -> None:
    """Forward legacy event topics onto ``events.external_feed``."""

    if bus in _BRIDGED_BUSES:
        return
    _BRIDGED_BUSES.add(bus)

    async def _forward_binance_listing(payload: Dict[str, Any]) -> None:
        try:
            envelope = ExternalEvent(
                source="binance_announcements",
                payload=payload if isinstance(payload, dict) else {"legacy": payload},
                meta={"bridge": "events.binance_listing"},
            ).with_default_id()
            await publish_external_event(
                envelope,
                asset_hints=([payload.get("symbol")] if isinstance(payload, dict) else None),
            )
        except Exception:  # noqa: BLE001
            _LOG.exception("Failed to bridge events.binance_listing payload")

    bus.subscribe("events.binance_listing", _forward_binance_listing)
    _LOG.info("Legacy topic 'events.binance_listing' bridged to events.external_feed")
