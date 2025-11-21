import asyncio

from engine.compat.events_bridge import init_external_feed_bridge
from engine.core.event_bus import EventBus
from engine.core.signal_queue import SIGNAL_QUEUE
from engine.events.publisher import publish_external_event
from engine.events.schemas import ExternalEvent


def test_external_event_routing_behaviour():
    async def _run():
        # Fan-out behaviour
        bus = EventBus()
        await bus.start()
        SIGNAL_QUEUE.start(bus)
        try:
            received_one = []
            received_two = []

            async def handler_one(evt):
                received_one.append(evt)

            async def handler_two(evt):
                received_two.append(evt)

            bus.subscribe("events.external_feed", handler_one)
            bus.subscribe("events.external_feed", handler_two)

            event = ExternalEvent(source="binance_announcements", payload={"symbol": "XYZUSDT"})
            await publish_external_event(event)
            for _ in range(10):
                if received_one and received_two:
                    break
                await asyncio.sleep(0.05)

            assert received_one and received_two
            assert received_one[0]["source"] == "binance_announcements"
            assert received_two[0]["payload"]["symbol"] == "XYZUSDT"
        finally:
            await SIGNAL_QUEUE.stop()
            await bus.stop()

        # Legacy bridge behaviour on the same loop
        bus_legacy = EventBus()
        await bus_legacy.start()
        SIGNAL_QUEUE.start(bus_legacy)
        init_external_feed_bridge(bus_legacy)
        try:
            bridged_events = []

            async def sink(evt):
                bridged_events.append(evt)

            bus_legacy.subscribe("events.external_feed", sink)

            await bus_legacy.publish("events.binance_listing", {"symbol": "ABCUSDT"})
            for _ in range(10):
                if bridged_events:
                    break
                await asyncio.sleep(0.05)

            assert bridged_events
            assert bridged_events[0]["payload"]["symbol"] == "ABCUSDT"
            assert bridged_events[0]["source"] == "binance_announcements"
        finally:
            await SIGNAL_QUEUE.stop()
            await bus_legacy.stop()

    asyncio.run(_run())
