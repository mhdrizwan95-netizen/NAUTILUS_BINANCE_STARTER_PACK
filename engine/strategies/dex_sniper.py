"""
DEX Sniper strategy.

Consumes tiered candidate events from the Dexscreener feed and, when enabled,
opens lightweight tracked positions via the stub executor.  The goal is to
provide end-to-end wiring (candidate -> execution intent -> state persistence)
so real swap adapters can be dropped in later without touching orchestration.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from engine.core.event_bus import BUS
from engine.dex import DexConfig, DexExecutor, DexState

logger = logging.getLogger("engine.strategies.dex_sniper")
_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class DexSniperConfigurationError(RuntimeError):
    """Raised when DexSniper is misconfigured."""

    def __init__(self) -> None:
        super().__init__("DexExecutor instance is required")


class DexSniper:
    def __init__(
        self,
        cfg: DexConfig,
        state: DexState | None = None,
        executor: DexExecutor | None = None,
    ) -> None:
        self.cfg = cfg
        self.state = state or DexState(cfg.state_path)
        if executor is None:
            raise DexSniperConfigurationError()
        self.executor = executor

    # --------------------------------------------------------------------- helpers
    def _limit_hit(self, symbol: str) -> bool:
        if self.state.count_open() >= self.cfg.max_live_positions:
            logger.debug("[DEX] limit hit (%s open)", self.state.count_open())
            return True
        if self.state.has_open(symbol):
            logger.debug("[DEX] %s already open; skipping", symbol)
            return True
        return False

    def _sanitize_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _validate_candidate(self, payload: dict[str, Any]) -> bool:
        liq = self._sanitize_float(payload.get("liq") or payload.get("liquidity"))
        if liq and liq < self.cfg.min_liq_usd:
            logger.debug("[DEX] liquidity %.0f below floor %.0f", liq, self.cfg.min_liq_usd)
            return False
        meta = payload.get("meta") or {}
        tax = self._sanitize_float(meta.get("tax_pct") or payload.get("tax_pct"))
        if tax and tax > self.cfg.tax_max_pct:
            logger.debug("[DEX] tax %.2f > max %.2f", tax, self.cfg.tax_max_pct)
            return False
        top10 = self._sanitize_float(meta.get("top10_pct") or payload.get("top10_pct"))
        if top10 and top10 > self.cfg.max_top10_pct:
            logger.debug("[DEX] top10 %.2f > max %.2f", top10, self.cfg.max_top10_pct)
            return False
        chain = str(payload.get("chain") or "").upper()
        if self.cfg.chain_whitelist and chain not in self.cfg.chain_whitelist:
            logger.debug("[DEX] chain %s not in whitelist %s", chain, self.cfg.chain_whitelist)
            return False
        return True

    def _targets(self) -> Iterable[tuple[float, float]]:
        return self.cfg.tp_targets

    async def handle_candidate(self, payload: dict[str, Any]) -> bool:
        if not self.cfg.exec_enabled:
            return False

        symbol = str(payload.get("symbol") or "").upper()
        chain = str(payload.get("chain") or "").upper()
        token_addr = str(
            payload.get("addr") or payload.get("token_address") or payload.get("address") or ""
        )
        tier = str(payload.get("tier") or "B").upper()
        payload.get("price") or (payload.get("meta") or {}).get("price")

        if not symbol or not chain:
            logger.debug("[DEX] candidate missing symbol/chain: %s", payload)
            return False
        if not token_addr:
            logger.debug("[DEX] candidate missing token address: %s", payload)
            return False
        if self._limit_hit(symbol):
            return False
        if not self._validate_candidate(payload):
            return False

        notional = self.cfg.size_tier_a if tier == "A" else self.cfg.size_tier_b
        if notional <= 0:
            logger.debug("[DEX] notional <= 0; skipping %s", symbol)
            return False

        try:
            fill = await self.executor.buy(
                symbol=symbol, token_address=token_addr, notional_usd=notional
            )
        except Exception as exc:
            logger.warning("[DEX] execution failed for %s: %s", symbol, exc)
            return False

        position = self.state.open_position(
            symbol=symbol,
            chain=chain,
            address=token_addr,
            tier=tier,
            qty=fill.qty,
            entry_price=fill.price,
            notional=fill.notional,
            stop_loss_pct=self.cfg.stop_loss_pct,
            trail_pct=self.cfg.trail_pct,
            metadata={
                "source": "dex_sniper",
                "candidate": payload,
                "initial_qty": fill.qty,
                "high_price": fill.price,
            },
            targets=self._targets(),
        )
        await self._emit_open_event(position)
        return True

    async def _emit_open_event(self, position) -> None:
        try:
            await BUS.publish(
                "strategy.dex_open",
                {
                    "symbol": position.symbol,
                    "qty": position.qty,
                    "price": position.entry_price,
                    "tier": position.tier,
                    "pos_id": position.pos_id,
                },
            )
        except Exception as exc:
            logger.debug(
                "[DEX] failed to publish open event for %s", position.symbol, exc_info=True
            )

    # --------------------------------------------------------------------- public
    async def flatten_all(self) -> None:
        """Synthetic close of all open positions (stub)."""
        for pos in list(self.state.open_positions()):
            try:
                await self.executor.sell(symbol=pos.symbol, token_address=pos.address, qty=pos.qty)
            except Exception as exc:
                logger.warning("[DEX] flatten failed for %s", pos.symbol, exc_info=True)
            self.state.close_position(pos.pos_id, reason="flatten_all")

    def active_symbols(self) -> list[str]:
        return [pos.symbol for pos in self.state.open_positions()]
