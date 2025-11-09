"""Backwards compatibility bridge for legacy external event topics."""

from __future__ import annotations

import logging
import weakref
from typing import Any

from engine.events.publisher import publish_external_event
from engine.events.schemas import ExternalEvent

_LOG = logging.getLogger("engine.compat.events_bridge")
_BRIDGE_ERRORS = (
    AttributeError,
    ConnectionError,
    RuntimeError,
    ValueError,
)
_BRIDGED_BUSES: weakref.WeakSet = weakref.WeakSet()


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOG.debug("%s suppressed: %s", context, exc, exc_info=True)


def init_external_feed_bridge(bus) -> None:
    """Forward legacy event topics onto ``events.external_feed``."""

    if bus in _BRIDGED_BUSES:
        return
    _BRIDGED_BUSES.add(bus)

    async def _forward_binance_listing(payload: dict[str, Any]) -> None:
        try:
            envelope = ExternalEvent(
                source="binance_announcements",
                payload=payload if isinstance(payload, dict) else {"legacy": payload},
                meta={"bridge": "events.binance_listing"},
            ).with_default_id()
            asset_hint = None
            if isinstance(payload, dict):
                symbol = payload.get("symbol")
                if isinstance(symbol, str) and symbol:
                    asset_hint = [symbol]
            await publish_external_event(
                envelope,
                asset_hints=asset_hint,
            )
        except _BRIDGE_ERRORS as exc:
            _log_suppressed("events_bridge.forward_binance_listing", exc)

    bus.subscribe("events.binance_listing", _forward_binance_listing)
    _LOG.info("Legacy topic 'events.binance_listing' bridged to events.external_feed")
