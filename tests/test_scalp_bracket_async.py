import asyncio
from typing import Any, Dict, List

from engine.runtime import tasks
from engine.strategies.scalp.brackets import ScalpBracketManager


class DummyFetcher:
    def __init__(self, values: List[float | None]) -> None:
        self._values = values
        self._idx = 0

    async def __call__(self, symbol: str) -> float | None:
        await asyncio.sleep(0)
        value = self._values[min(self._idx, len(self._values) - 1)]
        self._idx += 1
        return value


class DummyLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def exception(self, *args: Any, **kwargs: Any) -> None:
        pass

def test_scalp_bracket_manager_triggers_exit() -> None:
    async def _run() -> None:
        fetcher = DummyFetcher([None, 99.0, 101.2])
        exits: List[Dict[str, Any]] = []

        async def submit_exit(payload: Dict[str, Any]) -> None:
            exits.append(payload)

        mgr = ScalpBracketManager(price_fetcher=fetcher, submit_exit=submit_exit, logger=DummyLogger())
        mgr.watch(
            key="order-1",
            symbol="BTCUSDT.BINANCE",
            venue="BINANCE",
            entry_side="BUY",
            exit_side="SELL",
            quantity=1.0,
            stop_price=95.0,
            take_profit_price=100.0,
            poll_interval=0.01,
            ttl=0.5,
            tag_prefix="scalp",
        )

        await asyncio.sleep(0.1)

        assert exits, "expected exit callback to be invoked"
        assert exits[0]["tag"] == "scalp_tp"
        assert exits[0]["meta"]["trigger"] == "tp"

        await tasks.shutdown()

    asyncio.run(_run())
