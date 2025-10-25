"""
Real-time Event Bus - The Nervous System of Our Trading Organism.

Provides async pub/sub messaging for instantaneous inter-module communication,
turning reactive components into a coordinated trading intelligence.
"""
import asyncio
import logging
import json
from typing import Dict, List, Callable, Any, Optional


class EventBus:
    """
    Async pub/sub event bus for real-time inter-module communication.

    Design Philosophy:
    - Push-based reactive updates (no polling)
    - Async processing for low latency
    - Structured event schemas for consistency
    - Fault-tolerant with error isolation
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._stats = {
            "published": 0,
            "delivered": 0,
            "failed": 0,
            "topics": set()
        }

    async def start(self) -> None:
        """Start the event processing loop."""
        if self._running:
            return

        self._running = True
        logging.info("[BUS] Event bus started - ready for real-time coordination")
        asyncio.create_task(self._process_events())

    async def stop(self) -> None:
        """Gracefully stop the event processing."""
        self._running = False
        # Allow pending events to be processed
        await asyncio.sleep(0.1)
        logging.info(f"[BUS] Stopped. Stats: {self._stats}")

    def subscribe(self, topic: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Subscribe to events on a topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
            self._stats["topics"].add(topic)

        self._subscribers[topic].append(handler)
        logging.debug(f"[BUS] Subscribed to '{topic}' - {len(self._subscribers[topic])} handlers")

    def unsubscribe(self, topic: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Unsubscribe from a topic."""
        if topic in self._subscribers:
            try:
                self._subscribers[topic].remove(handler)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
                logging.debug(f"[BUS] Unsubscribed from '{topic}'")
            except ValueError:
                pass  # Handler not found

    async def publish(self, topic: str, data: Dict[str, Any], urgent: bool = False) -> None:
        """
        Publish an event to all subscribers.

        Args:
            topic: Event topic (e.g., "order.submitted", "risk.violation")
            data: Event payload with event-specific fields
            urgent: If True, process immediately rather than queue
        """
        if not self._running:
            return  # No-op if not started

        event = {
            "topic": topic,
            "data": data,
            "timestamp": asyncio.get_event_loop().time(),
            "source": "engine"  # Could be enhanced for multi-instance tracking
        }

        if urgent:
            await self._deliver_event(event)
        else:
            await self._queue.put(event)

        self._stats["published"] += 1

        # Debug logging for significant events
        if topic in {"order.submitted", "order.filled", "risk.violation", "strategy.promoted"}:
            logging.info(f"[BUS] 📢 {topic}: {data}")

    async def _process_events(self) -> None:
        """Main event processing loop."""
        while self._running or not self._queue.empty():
            try:
                # Timeout to allow shutdown
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._deliver_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logging.error(f"[BUS] Queue processing error: {e}")

    async def _deliver_event(self, event: Dict[str, Any]) -> None:
        """Deliver event to all subscribers with error isolation."""
        topic = event["topic"]
        data = event["data"]

        if topic not in self._subscribers:
            return  # No subscribers for this topic

        delivered = 0
        failed = 0

        for handler in self._subscribers[topic]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    # Run sync handlers in thread pool
                    await asyncio.get_event_loop().run_in_executor(None, handler, data)

                delivered += 1
            except Exception as e:
                failed += 1
                logging.error(f"[BUS] Handler error on '{topic}': {e}")

        self._stats["delivered"] += delivered
        self._stats["failed"] += failed

        if failed > 0:
            logging.warning(f"[BUS] {topic}: {delivered}/{len(self._subscribers[topic])} handlers succeeded")

    def get_stats(self) -> Dict[str, Any]:
        """Get bus statistics."""
        return {
            **self._stats,
            "active_subscriptions": sum(len(handlers) for handlers in self._subscribers.values()),
            "topics_count": len(self._stats["topics"]),
            "queue_size": self._queue.qsize(),
            "running": self._running
        }

    def fire(self, topic: str, data: Dict[str, Any]) -> None:
        """Fire-and-forget publish for non-async contexts.

        Schedules an async publish on the running loop. If no loop is
        running (rare in tests), it falls back to a best-effort direct
        call that will no-op when the bus isn't started.
        """
        async def _runner():
            try:
                await self.publish(topic, data)
            except Exception as e:
                logging.getLogger(__name__).warning("[BUS] fire error on %s: %s", topic, e)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_runner())
        except RuntimeError:
            # No running loop; invoke synchronously best-effort
            try:
                asyncio.run(_runner())
            except RuntimeError:
                # Nested loop not allowed; drop silently
                pass


# Global event bus instance - the central nervous system
BUS = EventBus()


# Convenience functions for common event publishing
async def publish_order_event(order_type: str, data: Dict[str, Any]) -> None:
    """Publish order-related events."""
    await BUS.publish(f"order.{order_type}", data)


async def publish_risk_event(event_type: str, data: Dict[str, Any]) -> None:
    """Publish risk-related events."""
    await BUS.publish(f"risk.{event_type}", data)


async def publish_strategy_event(event_type: str, data: Dict[str, Any]) -> None:
    """Publish strategy-related events."""
    await BUS.publish(f"strategy.{event_type}", data)


async def publish_metrics_event(data: Dict[str, Any]) -> None:
    """Publish metrics update events."""
    await BUS.publish("metrics.update", data)


# Startup integration
async def initialize_event_bus() -> None:
    """Start the global event bus."""
    await BUS.start()


async def shutdown_event_bus() -> None:
    """Gracefully shutdown the event bus."""
    await BUS.stop()
