from __future__ import annotations

import argparse
import asyncio
import time
from typing import Iterable

from engine.runtime.pipeline import Signal


async def burst(
    pipeline,
    strategy: str,
    symbol: str,
    count: int,
    delay: float,
    side: str = "BUY",
    confidence: float = 0.95,
) -> None:
    side = side.upper()
    for _ in range(count):
        sig = Signal(strategy=strategy, symbol=symbol, side=side, confidence=confidence, ttl=60)
        await pipeline.queue.put((sig, time.time()))
        if delay:
            await asyncio.sleep(delay)


async def multi_strategy_burst(
    pipeline,
    strategies: Iterable[str],
    symbols: Iterable[str],
    batches: int,
    per_batch: int,
    delay: float,
) -> None:
    symbols = list(symbols)
    for _ in range(batches):
        for strat, sym in zip(strategies, symbols):
            await burst(pipeline, strat, sym, per_batch, delay)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject synthetic bursts into a strategy pipeline")
    parser.add_argument("strategy", help="Strategy name (e.g. trend)")
    parser.add_argument("symbol", help="Qualified symbol (e.g. AAAUSDT)")
    parser.add_argument("count", type=int, help="Number of signals to enqueue")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between signals")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--confidence", type=float, default=0.95)
    return parser.parse_args()


# This module is typically imported and used within synthetic_feed harness.
# Providing a CLI stub for completeness.
def main(pipeline=None) -> None:
    if pipeline is None:
        raise RuntimeError(
            "burst_signals CLI expects to be invoked from synthetic harness with a pipeline"
        )
    args = parse_args()
    asyncio.run(
        burst(
            pipeline,
            args.strategy,
            args.symbol,
            args.count,
            args.delay,
            args.side,
            args.confidence,
        )
    )


__all__ = ["burst", "multi_strategy_burst"]
