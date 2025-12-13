from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any

import httpx


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger("engine.stop_validator").debug(
        "%s suppressed: %s", context, exc, exc_info=True
    )


_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    asyncio.TimeoutError,
    httpx.HTTPError,
)


class _ProtView:
    def __init__(self, items: list[dict] | None):
        self.items = items or []

    def has_stop_for(self, side: str) -> bool:
        want = "SELL" if side.upper() == "LONG" else "BUY"
        for it in self.items:
            t = str(it.get("type", it.get("orderType", ""))).upper()
            s = str(it.get("side", "")).upper()
            if ("STOP" in t) and s == want:
                return True
        return False

    def has_tp_at(self, price: float, tol: float = 1e-8) -> bool:
        for it in self.items:
            t = str(it.get("type", it.get("orderType", ""))).upper()
            p = float(it.get("price", 0.0) or 0.0)
            if ("LIMIT" in t) and abs(p - float(price)) <= tol:
                return True
        return False


class StopValidator:
    def __init__(self, cfg: dict, router, md, log, metrics, bus=None, clock=None) -> None:
        self.cfg = cfg
        self.router = router
        self.md = md
        self.log = log
        self.metrics = metrics
        self.bus = bus
        import time as _t

        self.clock = clock or _t
        self._last_alert: dict[str, float] = {}
        # Subscribe to fast-path fill events when bus provided
        try:
            if bus is not None:
                bus.subscribe("trade.fill", self.on_fill)
        except Exception as exc:
            _log_suppressed("stop validator subscribe", exc)

    async def on_fill(self, evt: dict) -> None:
        if not bool(self.cfg.get("STOP_VALIDATOR_ENABLED", False)):
            return
        await asyncio.sleep(int(self.cfg.get("STOP_VALIDATOR_GRACE_SEC", 2)))
        await self._validate_symbol(str(evt.get("symbol", "")))

    def _inc_metric(self, attr: str, **labels: Any) -> None:
        metric = getattr(self.metrics, attr, None)
        if metric is None:
            return
        try:
            metric.labels(**labels).inc()
        except Exception as exc:
            _log_suppressed(f"{attr} metric", exc)

    async def _fetch_protection(self, symbol: str) -> _ProtView:
        list_fn: Callable[[str], Iterable[dict]] | None = getattr(
            self.router, "list_open_protection", None
        )
        if not callable(list_fn):
            return _ProtView(None)
        try:
            items = await list_fn(symbol)
        except Exception as exc:
            _log_suppressed("list_open_protection", exc)
            return _ProtView(None)
        return _ProtView(list(items) if isinstance(items, list) else None)

    def _market_refs(self, symbol: str) -> tuple[float, float]:
        try:
            atr = float(self.md.atr(symbol, tf="1m", n=14) or 0.0)
            last = float(self.md.last(symbol) or 0.0)
        except Exception as exc:
            _log_suppressed("stop validator market refs", exc)
            return 0.0, 0.0
        return atr, last

    async def _notify_repair(self, symbol: str, price: float) -> None:
        if not bool(self.cfg.get("STOPVAL_NOTIFY_ENABLED", False)) or self.bus is None:
            return
        now = float(self.clock.time())
        last = self._last_alert.get(symbol, 0.0)
        if now - last < int(self.cfg.get("STOPVAL_NOTIFY_DEBOUNCE_SEC", 60)):
            return
        try:
            self.bus.fire(
                "notify.telegram",
                {"text": "\ud83d\udee1\ufe0f Stop repaired on *%s* at `%s`" % (symbol, price)},
            )
            if hasattr(self.metrics, "stop_validator_alerts_total"):
                self.metrics.stop_validator_alerts_total.labels(symbol=symbol, kind="SL").inc()
        except Exception as exc:
            _log_suppressed("stop validator notify", exc)
            return
        self._last_alert[symbol] = now

    async def run(self) -> None:
        if not bool(self.cfg.get("STOP_VALIDATOR_ENABLED", False)):
            return
        while True:
            try:
                await self._sweep_positions()
            except Exception as exc:
                _log_suppressed("stop validator sweep loop", exc)
            await asyncio.sleep(int(self.cfg.get("STOP_VALIDATOR_INTERVAL_SEC", 5)))

    async def _sweep_positions(self) -> None:
        try:
            state = self.router.portfolio_service().state
        except Exception as exc:
            _log_suppressed("stop validator state sweep", exc)
            return
        for sym, pos in (state.positions or {}).items():
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
            if qty == 0.0:
                continue
            await self._validate_symbol(sym)

    async def _validate_symbol(self, symbol: str) -> None:
        if not symbol:
            return
        try:
            state = self.router.portfolio_service().state
        except Exception as exc:
            _log_suppressed("stop validator state fetch", exc)
            return
        pos = state.positions.get(symbol) or state.positions.get(symbol.split(".")[0])
        if pos is None:
            return
        qty = float(getattr(pos, "quantity", 0.0) or 0.0)
        if qty == 0.0:
            return
        side = "LONG" if qty > 0 else "SHORT"
        prot = await self._fetch_protection(symbol)
        atr, last = self._market_refs(symbol)
        want_sl = (last - atr) if side == "LONG" else (last + atr)
        if prot.has_stop_for(side):
            return
        self._inc_metric("stop_validator_missing_total", symbol=symbol, kind="SL")
        if not bool(self.cfg.get("STOP_VALIDATOR_REPAIR", False)):
            return
        try:
            await self.router.amend_stop_reduce_only(
                symbol,
                "SELL" if side == "LONG" else "BUY",
                want_sl,
                abs(qty),
            )
        except Exception as exc:
            self.log.exception("[STOPVAL] Repair failed for %s", symbol)
            return
        self._inc_metric("stop_validator_repaired_total", symbol=symbol, kind="SL")
        self.log.warning("[STOPVAL] Repaired SL %s", symbol)
        await self._notify_repair(symbol, want_sl)
