from __future__ import annotations

"""Market data dispatcher that bridges WebSocket streams into the event bus."""

import logging
import time
from typing import Any, Callable, Dict, Optional

from engine.core.event_bus import EventBus
from engine import metrics

logger = logging.getLogger("engine.market_data.dispatcher")


class MarketDataDispatcher:
    """Publish normalized market data events onto the real-time event bus."""

    def __init__(self, bus: EventBus, *, source: str, venue: str = "BINANCE") -> None:
        self.bus = bus
        self.source = source
        self.venue = venue
        self._log = logger

    def handle_stream_event(self, event: Dict[str, Any]) -> None:
        """Handle a message emitted by the WebSocket client."""
        if not isinstance(event, dict):
            return
        topic = self._topic_for_event(event.get("type"))
        if not topic:
            return
        enriched = dict(event)
        enriched.setdefault("source", self.source)
        enriched.setdefault("venue", self.venue)
        enriched.setdefault("ts", time.time())
        try:
            evt_type = str(enriched.get("type") or "tick").lower()
            metrics.market_data_events_total.labels(
                source=self.source, type=evt_type
            ).inc()
        except Exception:
            pass
        try:
            self.bus.fire(topic, enriched)
        except Exception:
            self._log.debug("Failed to dispatch market data event", exc_info=True)

    @staticmethod
    def _topic_for_event(event_type: Optional[str]) -> Optional[str]:
        if not event_type:
            return "market.tick"
        normalized = str(event_type).lower()
        if normalized == "trade":
            return "market.trade"
        if normalized == "book":
            return "market.book"
        if normalized == "tick":
            return "market.tick"
        return None


class MarketDataLogger:
    """Simple bus consumer that logs tick events for observability."""

    def __init__(
        self,
        bus: EventBus,
        *,
        sample_rate_hz: float = 5.0,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.bus = bus
        self._log = logger or logging.getLogger("engine.market_data.logger")
        self._handler: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._min_interval = (
            0.0 if sample_rate_hz <= 0 else max(0.01, 1.0 / float(sample_rate_hz))
        )
        self._last_logged = 0.0

    def start(self) -> None:
        if self._handler is not None:
            return

        async def _handle(event: Dict[str, Any]) -> None:
            now = time.monotonic()
            if now - self._last_logged < self._min_interval:
                return
            self._last_logged = now
            symbol = str(event.get("symbol") or "")
            price = event.get("price")
            ts = event.get("ts")
            self._log.info("[MD] %s price=%s ts=%s", symbol, price, ts)

        self._handler = _handle
        self.bus.subscribe("market.tick", _handle)

    def stop(self) -> None:
        if self._handler is None:
            return
        try:
            self.bus.unsubscribe("market.tick", self._handler)
        finally:
            self._handler = None
