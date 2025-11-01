from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from engine.runtime import tasks

ExitCallback = Callable[[Dict[str, Any]], Awaitable[None]]
PriceFetcher = Callable[[str], float]


def _is_async_callable(fn: Callable[..., Any]) -> bool:
    call = getattr(fn, "__call__", None)
    if asyncio.iscoroutinefunction(fn):
        return True
    if call and asyncio.iscoroutinefunction(call):
        return True
    return False


class ScalpBracketManager:
    """Manage asynchronous stop/take-profit watchers for scalp fills."""

    def __init__(
        self,
        *,
        price_fetcher: PriceFetcher,
        submit_exit: ExitCallback,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._price_fetcher = price_fetcher
        self._price_fetcher_async = _is_async_callable(price_fetcher)
        self._exit_callback = submit_exit
        self._tasks: Dict[str, asyncio.Task[Any]] = {}
        self._log = logger or logging.getLogger(__name__)

    def watch(
        self,
        *,
        key: str,
        symbol: str,
        venue: str,
        entry_side: str,
        exit_side: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
        poll_interval: float,
        ttl: float,
        tag_prefix: str = "scalp",
    ) -> None:
        if key in self._tasks and not self._tasks[key].done():
            return

        task = tasks.spawn(
            self._watch_loop(
                key=key,
                symbol=symbol,
                venue=venue,
                entry_side=entry_side,
                exit_side=exit_side,
                quantity=quantity,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                poll_interval=poll_interval,
                ttl=ttl,
                tag_prefix=tag_prefix,
            ),
            name=f"scalp-bracket:{symbol}:{key}",
        )
        self._tasks[key] = task

    async def stop(self, key: str) -> None:
        task = self._tasks.pop(key, None)
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _fetch_price(self, symbol: str) -> Optional[float]:
        try:
            if self._price_fetcher_async:
                result = await self._price_fetcher(symbol)  # type: ignore[misc]
            else:
                result = await asyncio.to_thread(self._price_fetcher, symbol)
            if result is None:
                return None
            return float(result)
        except Exception:
            return None

    async def _watch_loop(
        self,
        *,
        key: str,
        symbol: str,
        venue: str,
        entry_side: str,
        exit_side: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
        poll_interval: float,
        ttl: float,
        tag_prefix: str,
    ) -> None:
        deadline = time.time() + ttl
        triggered: Optional[str] = None
        try:
            while time.time() < deadline:
                price = await self._fetch_price(symbol)
                if price is None or price <= 0.0:
                    await asyncio.sleep(poll_interval)
                    continue

                if entry_side == "BUY":
                    if price >= take_profit_price:
                        triggered = "tp"
                    elif price <= stop_price:
                        triggered = "sl"
                else:
                    if price <= take_profit_price:
                        triggered = "tp"
                    elif price >= stop_price:
                        triggered = "sl"

                if triggered:
                    await self._submit(
                        triggered,
                        symbol,
                        venue,
                        exit_side,
                        quantity,
                        stop_price,
                        take_profit_price,
                        tag_prefix,
                    )
                    break

                await asyncio.sleep(poll_interval)

            if triggered is None:
                self._log.info(
                    "[SCALP] bracket timeout for %s side=%s qty=%.6f (stop=%.6f tp=%.6f)",
                    symbol,
                    entry_side,
                    quantity,
                    stop_price,
                    take_profit_price,
                )
        except asyncio.CancelledError:
            self._log.debug("Bracket watcher cancelled: %s", key)
            raise
        except Exception:
            self._log.exception("Bracket watcher error: %s", key)
        finally:
            self._tasks.pop(key, None)

    async def _submit(
        self,
        trigger: str,
        symbol: str,
        venue: str,
        exit_side: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float,
        tag_prefix: str,
    ) -> None:
        payload = {
            "symbol": symbol,
            "venue": venue,
            "side": exit_side,
            "quantity": quantity,
            "tag": f"{tag_prefix}_{trigger}",
            "meta": {
                "trigger": trigger,
                "stop_price": stop_price,
                "take_profit": take_profit_price,
            },
        }
        try:
            await self._exit_callback(payload)
        except Exception:
            self._log.warning(
                "[SCALP] exit submission failed for %s", symbol, exc_info=True
            )
