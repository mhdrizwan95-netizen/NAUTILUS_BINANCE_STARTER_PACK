from __future__ import annotations

import asyncio


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
        except Exception:
            pass

    async def on_fill(self, evt: dict) -> None:
        if not bool(self.cfg.get("STOP_VALIDATOR_ENABLED", False)):
            return
        await asyncio.sleep(int(self.cfg.get("STOP_VALIDATOR_GRACE_SEC", 2)))
        await self._validate_symbol(str(evt.get("symbol", "")))

    async def run(self) -> None:
        if not bool(self.cfg.get("STOP_VALIDATOR_ENABLED", False)):
            return
        while True:
            try:
                await self._sweep_positions()
            except Exception:
                pass
            await asyncio.sleep(int(self.cfg.get("STOP_VALIDATOR_INTERVAL_SEC", 5)))

    async def _sweep_positions(self) -> None:
        try:
            st = self.router.portfolio_service().state
            for sym, pos in (st.positions or {}).items():
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                if abs(qty) <= 0:
                    continue
                await self._validate_symbol(sym)
        except Exception:
            pass

    async def _validate_symbol(self, symbol: str) -> None:
        if not symbol:
            return
        try:
            st = self.router.portfolio_service().state
            pos = st.positions.get(symbol) or st.positions.get(symbol.split(".")[0])
            if pos is None:
                return
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
            side = "LONG" if qty > 0 else "SHORT"
            prot_items = None
            try:
                li = getattr(self.router, "list_open_protection", None)
                if callable(li):
                    prot_items = await li(symbol)
            except Exception:
                prot_items = None
            prot = _ProtView(prot_items if isinstance(prot_items, list) else None)

            # Desired SL price: use ATR fallback if not in state
            atr = 0.0
            last = 0.0
            try:
                atr = float(self.md.atr(symbol, tf="1m", n=14) or 0.0)
                last = float(self.md.last(symbol) or 0.0)
            except Exception:
                pass
            want_sl = (last - atr) if side == "LONG" else (last + atr)
            if not prot.has_stop_for(side):
                try:
                    self.metrics.stop_validator_missing_total.labels(symbol=symbol, kind="SL").inc()
                except Exception:
                    pass
                if bool(self.cfg.get("STOP_VALIDATOR_REPAIR", False)):
                    await self.router.amend_stop_reduce_only(
                        symbol, "SELL" if side == "LONG" else "BUY", want_sl, abs(qty)
                    )
                    try:
                        self.metrics.stop_validator_repaired_total.labels(
                            symbol=symbol, kind="SL"
                        ).inc()
                    except Exception:
                        pass
                    self.log.warning("[STOPVAL] Repaired SL %s", symbol)
                    # Optional notify bridge (debounced)
                    if bool(self.cfg.get("STOPVAL_NOTIFY_ENABLED", False)) and self.bus is not None:
                        now = float(self.clock.time())
                        last = self._last_alert.get(symbol, 0.0)
                        if now - last >= int(self.cfg.get("STOPVAL_NOTIFY_DEBOUNCE_SEC", 60)):
                            try:
                                self.bus.fire(
                                    "notify.telegram",
                                    {
                                        "text": f"\ud83d\udee1\ufe0f Stop repaired on *{symbol}* at `{want_sl}`"
                                    },
                                )
                                if hasattr(self.metrics, "stop_validator_alerts_total"):
                                    self.metrics.stop_validator_alerts_total.labels(
                                        symbol=symbol, kind="SL"
                                    ).inc()
                            except Exception:
                                pass
                            self._last_alert[symbol] = now
        except Exception:
            pass
