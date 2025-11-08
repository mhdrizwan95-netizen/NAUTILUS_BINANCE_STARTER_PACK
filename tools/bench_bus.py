#!/usr/bin/env python3
"""
Microbench: EventBus publish/deliver throughput.

Usage: python tools/bench_bus.py [n_events]
"""
import asyncio
import sys
import time

from engine.core.event_bus import BUS


async def noop(_):
    return None


async def main(n: int = 10000):
    await BUS.start()
    BUS.subscribe("bench", noop)
    t0 = time.perf_counter()
    for i in range(n):
        await BUS.publish("bench", {"i": i})
    # allow queue to drain
    await asyncio.sleep(0.1)
    t1 = time.perf_counter()
    print({"events": n, "elapsed_s": t1 - t0, "throughput_eps": n / max(t1 - t0, 1e-6)})
    await BUS.stop()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    asyncio.run(main(n))
