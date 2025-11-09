"""
Trailing and ladder watcher for DEX sniper positions.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from engine.dex.config import DexConfig
from engine.dex.executor import DexExecutor
from engine.dex.oracle import DexPriceOracle
from engine.dex.state import DexPosition, DexState

logger = logging.getLogger("engine.dex.watcher")
_WATCHER_ERRORS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


class DexWatcher:
    def __init__(
        self,
        cfg: DexConfig,
        state: DexState,
        executor: DexExecutor,
        oracle: DexPriceOracle,
    ) -> None:
        self.cfg = cfg
        self.state = state
        self.executor = executor
        self.oracle = oracle
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="dex-watcher")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            await self._task
        await self.oracle.close()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except _WATCHER_ERRORS as exc:
                _log_suppressed("dex.watcher.tick", exc)
            await asyncio.sleep(max(self.cfg.watcher_poll_sec, 1.0))

    async def tick(self) -> None:
        positions: Iterable[DexPosition] = list(self.state.open_positions())
        for pos in positions:
            await self._evaluate(pos)

    async def _evaluate(self, pos: DexPosition) -> None:
        token_identifier = (
            pos.address or (pos.metadata.get("candidate") or {}).get("addr") or pos.symbol
        )
        price = await self.oracle.price_usd(token_identifier)
        if price is None or price <= 0:
            return

        high = float(pos.metadata.get("high_price") or pos.entry_price)
        if price > high:
            high = price
            self.state.set_metadata(pos.pos_id, "high_price", high)

        # Stop loss check
        stop_price = pos.entry_price * (1 - pos.stop_loss_pct)
        if price <= stop_price:
            await self._flatten(pos, price, reason="stop_loss")
            return

        # Ladder targets
        for idx, target in enumerate(pos.tp_targets):
            if target.filled:
                continue
            trigger = pos.entry_price * (1 + target.pct)
            if price >= trigger:
                await self._take_partial(pos, idx, price)
                pos = self.state.refresh_position(pos.pos_id) or pos

        # Trailing remainder
        if pos.status != "open":
            return
        trail_price = high * (1 - pos.trail_pct)
        if price <= trail_price and high > pos.entry_price:
            await self._flatten(pos, price, reason="trailing_stop")

    async def _take_partial(self, pos: DexPosition, target_index: int, price: float) -> None:
        target = pos.tp_targets[target_index]
        base_qty = float(pos.metadata.get("initial_qty") or pos.qty)
        qty_to_sell = max(base_qty * target.portion, 0.0)
        qty_to_sell = min(qty_to_sell, pos.qty)
        if qty_to_sell <= 0:
            self.state.record_target_fill(pos.pos_id, target_index)
            return
        try:
            result = await self.executor.sell(
                symbol=pos.symbol,
                token_address=pos.address,
                qty=qty_to_sell,
            )
            logger.info(
                "[DEX] Partial TP hit %s qty=%.6f price=%.4f tx=%s",
                pos.symbol,
                qty_to_sell,
                result.price,
                result.tx_hash,
            )
            self.state.register_fill(
                pos.pos_id, qty_to_sell, target_index=target_index, reason="take_profit"
            )
        except _WATCHER_ERRORS as exc:
            _log_suppressed("dex.watcher.take_partial", exc)

    async def _flatten(self, pos: DexPosition, price: float, *, reason: str) -> None:
        qty = pos.qty
        if qty <= 0:
            self.state.close_position(pos.pos_id, reason=reason)
            return
        try:
            result = await self.executor.sell(symbol=pos.symbol, token_address=pos.address, qty=qty)
            logger.info(
                "[DEX] %s exit qty=%.6f price=%.4f tx=%s reason=%s",
                pos.symbol,
                qty,
                result.price,
                result.tx_hash,
                reason,
            )
        except _WATCHER_ERRORS as exc:
            _log_suppressed("dex.watcher.flatten", exc)
        finally:
            self.state.close_position(pos.pos_id, reason=reason)
