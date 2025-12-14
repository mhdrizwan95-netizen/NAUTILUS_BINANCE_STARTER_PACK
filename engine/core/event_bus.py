"""
Real-time Event Bus - The Nervous System of Our Trading Organism.

Provides async pub/sub messaging for instantaneous inter-module communication,
turning reactive components into a coordinated trading intelligence.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from engine import metrics


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger(__name__).warning("[BUS] %s suppressed: %s", context, exc, exc_info=True)


_QUEUE_ENV_ERRORS: tuple[type[Exception], ...] = (TypeError, ValueError)
_PROCESS_ERRORS: tuple[type[Exception], ...] = (asyncio.CancelledError, OSError, ValueError)
_PUBLISH_ERRORS: tuple[type[Exception], ...] = (RuntimeError, asyncio.CancelledError)
_METRIC_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError)


def _is_async_callable(obj: Callable[[dict[str, Any]], Any]) -> bool:
    """Return True when the callable is async, including async __call__ objects."""
    if inspect.iscoroutinefunction(obj):
        return True
    if not callable(obj):
        return False
    if not callable(obj):
        return False
    try:
        return inspect.iscoroutinefunction(obj.__call__)  # type: ignore[attr-defined]
    except AttributeError:
        return False


def _call_sync(handler: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
    """Execute the synchronous handler. Runs inside the thread pool."""
    return handler(payload)


class EventBus:
    """
    Async pub/sub event bus for real-time inter-module communication.

    Design Philosophy:
    - Push-based reactive updates (no polling)
    - Async processing for low latency
    - Structured event schemas for consistency
    - Fault-tolerant with error isolation
    """

    def __init__(self, max_workers: int | None = None):
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self._queue: asyncio.Queue | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stats = {"published": 0, "delivered": 0, "failed": 0, "topics": set()}
        if max_workers is None:
            max_workers = int(os.getenv("EVENTBUS_MAX_WORKERS", "8"))
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._worker: asyncio.Task[Any] | None = None
        try:
            self._queue_max = max(0, int(os.getenv("EVENTBUS_QUEUE_MAX", "2000")))
        except _QUEUE_ENV_ERRORS as exc:
            _log_suppressed("queue capacity parse", exc)
            self._queue_max = 2000
        
        # [Phase 7 Fix] Concurrency Control
        self._active_tasks: set[asyncio.Task] = set()
        self._concurrency_limit = asyncio.Semaphore(100) # Max 100 concurrent events

    async def start(self) -> None:
        """Start the event processing loop."""
        if self._running:
            return

        loop = asyncio.get_running_loop()
        self._loop = loop
        # Bounded queue provides backpressure under bursty load instead of RAM growth
        self._queue = asyncio.Queue(maxsize=self._queue_max or 0)
        self._running = True
        logging.info("[BUS] Event bus started - ready for real-time coordination")
        self._worker = asyncio.create_task(self._process_events())

    async def stop(self) -> None:
        """Gracefully stop the event processing."""
        self._running = False
        # Allow pending events to be processed
        await asyncio.sleep(0.1)
        logging.info(f"[BUS] Stopped. Stats: {self._stats}")
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                await worker
            except asyncio.CancelledError:
                pass
            except RuntimeError:
                pass
        
        # Wait for active handlers to finish
        if self._active_tasks:
            logging.info(f"[BUS] Waiting for {len(self._active_tasks)} active event tasks...")
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            
        self._queue = None
        self._loop = None

    def shutdown(self, wait: bool = False) -> None:
        """Tear down the executor. Useful for tests or process shutdown."""
        self._executor.shutdown(wait=wait)

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Subscribe to events on a topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
            self._stats["topics"].add(topic)

        self._subscribers[topic].append(handler)
        logging.debug(f"[BUS] Subscribed to '{topic}' - {len(self._subscribers[topic])} handlers")

    def unsubscribe(self, topic: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Unsubscribe from a topic."""
        if topic in self._subscribers:
            try:
                self._subscribers[topic].remove(handler)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
                logging.debug(f"[BUS] Unsubscribed from '{topic}'")
            except ValueError:
                pass  # Handler not found

    async def publish(self, topic: str, data: dict[str, Any], urgent: bool = False) -> None:
        """
        Publish an event to all subscribers.

        Args:
            topic: Event topic (e.g., "order.submitted", "risk.violation")
            data: Event payload with event-specific fields
            urgent: If True, process immediately rather than queue
        """
        if not self._running:
            logging.getLogger(__name__).debug(
                "EventBus publish skipped; bus not running (topic=%s)", topic
            )
            return  # No-op if not started

        queue = self._queue
        if queue is None:
            logging.getLogger(__name__).debug(
                "EventBus publish skipped; queue not initialised (topic=%s)", topic
            )
            return

        event = {
            "topic": topic,
            "data": data,
            "timestamp": asyncio.get_event_loop().time(),
            "source": "engine",  # Could be enhanced for multi-instance tracking
        }

        if urgent:
            # Urgent events bypass connection limits and queue
            await self._deliver_event(event)
        else:
            await queue.put(event)

        self._stats["published"] += 1

        # Debug logging for significant events
        if topic in {
            "order.submitted",
            "order.filled",
            "risk.violation",
            "strategy.promoted",
        }:
            logging.info(f"[BUS] 📢 {topic}: {data}")

    async def _process_events(self) -> None:
        """Main event processing loop."""
        while True:
            queue = self._queue
            if queue is None:
                if not self._running:
                    break
                await asyncio.sleep(0.05)
                continue

            if not self._running and queue.empty():
                break
            try:
                # Timeout to allow shutdown
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                
                # [Phase 7 Fix] Non-blocking dispatch
                # Acquire semaphore slot (waits if full)
                await self._concurrency_limit.acquire()
                
                task = asyncio.create_task(self._deliver_event_wrapper(event))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)
                
            except TimeoutError:
                continue
            except RuntimeError:
                logging.exception("[BUS] Queue processing error (runtime)")
                break
            except _PROCESS_ERRORS as exc:
                _log_suppressed("process_events", exc)

    async def _deliver_event_wrapper(self, event: dict[str, Any]) -> None:
        """Wrapper to release semaphore after delivery."""
        try:
            await self._deliver_event(event)
        finally:
            self._concurrency_limit.release()

    async def _deliver_event(self, event: dict[str, Any]) -> None:
        """Deliver event to all subscribers with error isolation."""
        topic = event["topic"]
        data = event["data"]

        if topic not in self._subscribers:
            # logging.getLogger(__name__).debug("EventBus: no subscribers for topic %s", topic)
            return  # No subscribers for this topic

        delivered = 0
        failed = 0
        handlers = list(self._subscribers[topic])
        loop = asyncio.get_running_loop()
        pending = [self._dispatch_handler(handler, data, loop) for handler in handlers]
        results = await asyncio.gather(*pending, return_exceptions=True)

        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, Exception):
                failed += 1
                # func_name = getattr(handler, "__name__", str(handler))
                logging.error("[BUS] Handler error on '%s': %s", topic, result)
                continue

            delivered += 1
            if topic == "events.external_feed":
                try:
                    consumer = getattr(handler, "__qualname__", None) or getattr(
                        handler, "__name__", None
                    )
                    if not consumer and hasattr(handler, "__self__"):
                        consumer = handler.__self__.__class__.__name__
                    consumer = consumer or handler.__class__.__name__
                    metrics.events_external_feed_consumed_total.labels(consumer=consumer).inc()
                except _METRIC_ERRORS as exc:
                    _log_suppressed("metrics update", exc)

        self._stats["delivered"] += delivered
        self._stats["failed"] += failed

        if failed > 0:
            logging.warning(
                f"[BUS] {topic}: {delivered}/{len(self._subscribers[topic])} handlers succeeded"
            )

    def get_stats(self) -> dict[str, Any]:
        """Get bus statistics."""
        return {
            **self._stats,
            "active_subscriptions": sum(len(handlers) for handlers in self._subscribers.values()),
            "topics_count": len(self._stats["topics"]),
            "queue_size": self._queue.qsize() if self._queue is not None else 0,
            "running": self._running,
            "concurrency_slots_free": self._concurrency_limit._value if self._concurrency_limit else 0
        }

    def fire(self, topic: str, data: dict[str, Any]) -> None:
        """Fire-and-forget publish for non-async contexts.

        Schedules an async publish on the running loop. If no loop is
        running (rare in tests), it falls back to a best-effort direct
        call that will no-op when the bus isn't started.
        """

        async def _runner():
            try:
                await self.publish(topic, data)
            except _PUBLISH_ERRORS as exc:
                _log_suppressed(f"fire publish {topic}", exc)

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

    async def _dispatch_handler(
        self,
        handler: Callable[[dict[str, Any]], Any],
        payload: dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ) -> Any:
        """Dispatch handler execution via async/await or executor offloading."""
        if _is_async_callable(handler):
            # Async handlers are expected to be non-blocking; avoid deep-copy overhead
            return await handler(dict(payload))

        # Offload sync handlers to thread pool; isolate via deep copy
        return await loop.run_in_executor(
            self._executor, _call_sync, handler, copy.deepcopy(payload)
        )


# Global event bus instance - the central nervous system
BUS = EventBus()


# Convenience functions for common event publishing
async def publish_order_event(order_type: str, data: dict[str, Any]) -> None:
    """Publish order-related events."""
    await BUS.publish(f"order.{order_type}", data)


async def publish_risk_event(event_type: str, data: dict[str, Any]) -> None:
    """Publish risk-related events."""
    await BUS.publish(f"risk.{event_type}", data)


async def publish_strategy_event(event_type: str, data: dict[str, Any]) -> None:
    """Publish strategy-related events."""
    await BUS.publish(f"strategy.{event_type}", data)


async def publish_metrics_event(data: dict[str, Any]) -> None:
    """Publish metrics update events."""
    await BUS.publish("metrics.update", data)


# Startup integration
async def initialize_event_bus() -> None:
    """Start the global event bus."""
    await BUS.start()


async def shutdown_event_bus() -> None:
    """Gracefully shutdown the event bus."""
    await BUS.stop()
