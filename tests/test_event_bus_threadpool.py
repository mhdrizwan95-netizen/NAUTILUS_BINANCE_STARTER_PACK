import asyncio
import time

from engine.core.event_bus import EventBus


def _slow_sync_handler(collected):
    def _handler(evt):
        time.sleep(0.2)
        collected.append(("sync", evt["i"]))

    return _handler


async def _fast_async_probe(flag: asyncio.Event) -> None:
    await asyncio.sleep(0.05)
    flag.set()


def test_sync_handlers_do_not_block_loop():
    async def _run():
        bus = EventBus(max_workers=4)
        await bus.start()

        seen = []
        bus.subscribe("topic", _slow_sync_handler(seen))

        loop_flag = asyncio.Event()
        asyncio.create_task(_fast_async_probe(loop_flag))

        start = time.perf_counter()
        await bus.publish("topic", {"i": 1}, urgent=True)
        elapsed = time.perf_counter() - start

        assert loop_flag.is_set(), "event loop stalled by sync handler"
        assert seen == [("sync", 1)]
        assert elapsed >= 0.19

        await bus.stop()
        bus.shutdown(wait=False)

    asyncio.run(_run())


def test_async_and_sync_mix():
    async def _run():
        bus = EventBus(max_workers=2)
        await bus.start()

        order = []

        async def async_handler(evt):
            await asyncio.sleep(0.01)
            order.append(("async", evt["i"]))

        def sync_handler(evt):
            time.sleep(0.05)
            order.append(("sync", evt["i"]))

        bus.subscribe("mix", async_handler)
        bus.subscribe("mix", sync_handler)

        await bus.publish("mix", {"i": 7}, urgent=True)

        kinds = {k for k, _ in order}
        assert kinds == {"async", "sync"}

        await bus.stop()
        bus.shutdown(wait=False)

    asyncio.run(_run())
