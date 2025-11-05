from __future__ import annotations

import asyncio
import logging
import signal
from typing import Coroutine

from ..core.binance import BinanceREST
from ..core.order_router import OrderRouter
from ..core.portfolio import Portfolio
from .config import RuntimeConfig, load_runtime_config
from .pipeline import StrategyPipeline, StrategyRegistry
from .producers import (
    MomentumProducer,
    ScalperProducer,
    TrendProducer,
    VolatilityProducer,
)
from .universe import UniverseManager, UniverseScreener

log = logging.getLogger("engine.runtime.service")


def _register_default_strategies(registry: StrategyRegistry) -> None:
    registry.register("trend", lambda cfg, mgr: TrendProducer(cfg, mgr))
    registry.register("momentum", lambda cfg, mgr: MomentumProducer(cfg, mgr))
    registry.register("scalper", lambda cfg, mgr: ScalperProducer(cfg, mgr))
    registry.register("event", lambda cfg, mgr: VolatilityProducer(cfg, mgr))


async def _run_pipeline(config: RuntimeConfig) -> None:
    portfolio = Portfolio(starting_cash=10_000.0)
    rest_client = BinanceREST()
    router = OrderRouter(default_client=rest_client, portfolio=portfolio)
    try:
        await router.initialize_balances()
    except Exception:
        log.info(
            "[runtime] unable to pre-load balances; continuing with defaults",
            exc_info=True,
        )

    registry = StrategyRegistry()
    _register_default_strategies(registry)

    manager = UniverseManager(config)
    screener = UniverseScreener(config, rest_client, manager)
    screener.start()

    pipeline = StrategyPipeline(
        config=config,
        registry=registry,
        order_router=router,
        manager=manager,
    )
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _shutdown() -> None:
        log.info("[runtime] shutdown requested")
        pipeline.cancel()
        asyncio.create_task(screener.stop())
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            pass

    worker: Coroutine = pipeline.run()
    task = asyncio.create_task(worker, name="runtime-pipeline")
    await stop_event.wait()
    await asyncio.gather(task, return_exceptions=True)
    await screener.stop()


async def main() -> None:
    from engine.logging_utils import setup_logging

    setup_logging()
    config = load_runtime_config()
    log.info("[runtime] starting strategy pipeline (demo=%s)", config.demo_mode)
    await _run_pipeline(config)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
