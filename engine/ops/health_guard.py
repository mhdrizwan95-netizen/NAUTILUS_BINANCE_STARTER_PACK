from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from engine.config.env import env_bool, env_float
from engine.core.event_bus import BUS

_LOG = logging.getLogger("engine.ops.health_guard")
_SUPPRESSIBLE_GUARD_ERRORS = (
    asyncio.CancelledError,
    AttributeError,
    RuntimeError,
    ValueError,
    TypeError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    _LOG.warning("SOFT-BREACH suppressed %s: %s", context, exc, exc_info=True)


def _truthy(value: str | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class SoftBreachConfig:
    enabled: bool
    tighten_mult: float
    breakeven_ok: bool
    cancel_entries: bool
    log_orders: bool


class SoftBreachGuard:
    """Applies soft risk actions when the guardian raises a breach."""

    def __init__(self, router: Any, portfolio: Any | None = None) -> None:
        self.router = router
        self.portfolio = portfolio or getattr(router, "portfolio_service", lambda: None)()
        self.cfg = SoftBreachConfig(
            enabled=env_bool("SOFT_BREACH_ENABLED", True),
            tighten_mult=max(0.0, min(1.0, env_float("SOFT_BREACH_TIGHTEN_SL_PCT", 0.6))),
            breakeven_ok=env_bool("SOFT_BREACH_BREAKEVEN_OK", True),
            cancel_entries=env_bool("SOFT_BREACH_CANCEL_ENTRIES", True),
            log_orders=env_bool("SOFT_BREACH_LOG_ORDERS", True),
        )

    async def on_cross_health_soft(self, breach: dict[str, Any]) -> None:
        if not self.cfg.enabled:
            return

        kind = breach.get("kind") or breach.get("type") or "unknown"
        details = breach.get("details") or {}
        _LOG.info("SOFT-BREACH: kind=%s details=%s", kind, details)

        if self.cfg.cancel_entries:
            await self._cancel_entry_orders()

        await self._tighten_open_positions()

        try:
            await BUS.publish(
                "events.external_feed",
                {
                    "source": "soft_breach_guard",
                    "payload": {"kind": kind, "details": details},
                },
            )
        except _SUPPRESSIBLE_GUARD_ERRORS as exc:
            _log_suppressed("bus publish", exc)

    async def _cancel_entry_orders(self) -> None:
        orders = await self._list_open_orders()
        if not orders:
            _LOG.info("SOFT-BREACH: no entry orders to cancel")
            return

        cancelled = 0
        for order in orders:
            if not self._is_entry_order(order):
                continue
            try:
                ok = await self.router.cancel_open_order(order)
            except AttributeError:
                cancel = getattr(self.router, "cancel_order", None)
                if cancel is None:
                    ok = False
                else:
                    kwargs = self._cancel_kwargs(order)
                    res = cancel(**kwargs)
                    ok = await res if asyncio.iscoroutine(res) else bool(res)
            except _SUPPRESSIBLE_GUARD_ERRORS as exc:
                ok = False
                _log_suppressed("cancel entry order", exc)

            if ok:
                cancelled += 1
                if self.cfg.log_orders:
                    _LOG.info(
                        "SOFT-BREACH: cancelled entry id=%s symbol=%s side=%s",
                        order.get("orderId") or order.get("order_id"),
                        order.get("symbol"),
                        order.get("side"),
                    )

        if cancelled == 0 and self.cfg.log_orders:
            _LOG.info("SOFT-BREACH: no entry orders cancelled")

    async def _tighten_open_positions(self) -> None:
        positions = self._portfolio_positions()
        if not positions:
            _LOG.info("SOFT-BREACH: no positions to tighten")
            return

        orders = await self._list_open_orders()

        for pos in positions:
            try:
                await self._tighten_position(pos, orders)
            except _SUPPRESSIBLE_GUARD_ERRORS as exc:
                _log_suppressed(f"tighten position {pos.get('symbol')}", exc)

    async def _tighten_position(
        self, pos: dict[str, Any], orders: Iterable[dict[str, Any]] | None
    ) -> None:
        qty = float(pos.get("quantity") or pos.get("qty") or pos.get("qty_base") or 0.0)
        if abs(qty) <= 0:
            return

        symbol = str(pos.get("symbol") or "").upper()
        avg_price = float(pos.get("avg_price") or pos.get("avg_price_quote") or 0.0)
        if not symbol or avg_price <= 0:
            return

        side = "LONG" if qty > 0 else "SHORT"
        protective = self._matching_stop(symbol, orders or [])
        if protective is None:
            _LOG.info("SOFT-BREACH: %s has no active stop order", symbol)
            return

        current_stop = float(protective.get("stopPrice") or protective.get("price") or 0.0)
        if current_stop <= 0:
            return

        tighten_mult = self.cfg.tighten_mult
        if side == "LONG":
            distance = max(0.0, avg_price - current_stop)
            if distance == 0:
                return
            new_distance = distance * tighten_mult
            candidate = avg_price - new_distance
            if self.cfg.breakeven_ok:
                candidate = min(max(candidate, current_stop), avg_price)
            if candidate <= current_stop + 1e-8:
                return
        else:
            distance = max(0.0, current_stop - avg_price)
            if distance == 0:
                return
            new_distance = distance * tighten_mult
            candidate = avg_price + new_distance
            if self.cfg.breakeven_ok:
                candidate = max(min(candidate, current_stop), avg_price)
            if candidate >= current_stop - 1e-8:
                return

        amend_symbol = symbol if "." in symbol else f"{symbol}.BINANCE"
        amend_side = "SELL" if side == "LONG" else "BUY"

        try:
            await self.router.amend_stop_reduce_only(
                amend_symbol,
                amend_side,
                float(candidate),
                abs(qty),
            )
            if self.cfg.log_orders:
                _LOG.info(
                    "SOFT-BREACH: tightened stop %s side=%s old=%.6f new=%.6f",
                    symbol,
                    amend_side,
                    current_stop,
                    candidate,
                )
        except AttributeError:
            # Router lacks amend helper; attempt reduce-only placement
            place = getattr(self.router, "place_reduce_only_market", None)
            if place is None:
                raise
            await place(amend_symbol, amend_side, abs(qty))

    async def _list_open_orders(self) -> list[dict[str, Any]]:
        try:
            res = await self.router.list_open_entries()
        except AttributeError:
            fn = getattr(self.router, "list_open_orders", None)
            if fn is None:
                return []
            result = fn()
            res = await result if asyncio.iscoroutine(result) else result
        return list(res or [])

    def _portfolio_positions(self) -> list[dict[str, Any]]:
        state = getattr(self.portfolio, "state", None)
        if state is None:
            return []
        positions = getattr(state, "positions", {})
        values = []
        for key, pos in positions.items():
            try:
                values.append(
                    {
                        "symbol": getattr(pos, "symbol", key),
                        "quantity": getattr(pos, "quantity", 0.0),
                        "avg_price": getattr(pos, "avg_price", 0.0),
                    }
                )
            except _SUPPRESSIBLE_GUARD_ERRORS as exc:
                _log_suppressed("portfolio snapshot decode", exc)
                continue
        return values

    @staticmethod
    def _is_entry_order(order: dict[str, Any]) -> bool:
        meta = order.get("meta") or {}
        if isinstance(meta, dict) and str(meta.get("kind", "")).lower() in {
            "entry",
            "open",
        }:
            return True

        tag = str(order.get("tag") or order.get("clientOrderId") or "").lower()
        if "entry" in tag:
            return True

        order_type = str(order.get("type") or "").upper()
        if "STOP" in order_type or "TAKE_PROFIT" in order_type:
            return False

        reduce_only = order.get("reduceOnly")
        if isinstance(reduce_only, str):
            reduce_only = _truthy(reduce_only)
        if reduce_only:
            return False
        return True

    @staticmethod
    def _matching_stop(symbol: str, orders: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
        base = symbol.split(".")[0].upper()
        for order in orders:
            sym = str(order.get("symbol") or "").upper()
            if sym and sym.split(".")[0].upper() != base:
                continue
            order_type = str(order.get("type") or "").upper()
            if "STOP" not in order_type:
                continue
            if _truthy(order.get("reduceOnly")):
                return order
            meta = order.get("meta")
            if isinstance(meta, dict) and str(meta.get("kind", "")).lower() in {
                "stop",
                "protection",
            }:
                return order
        return None

    @staticmethod
    def _cancel_kwargs(order: dict[str, Any]) -> dict[str, Any]:
        symbol = str(order.get("symbol") or "").upper()
        order_id = order.get("orderId") or order.get("order_id")
        client_order_id = order.get("clientOrderId") or order.get("client_order_id")
        kwargs: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            kwargs["order_id"] = order_id
        if client_order_id:
            kwargs["client_order_id"] = client_order_id
        market = order.get("market") or order.get("venue")
        if market:
            kwargs["market"] = market
        return kwargs


__all__ = ["SoftBreachGuard"]
