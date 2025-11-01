from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, Set


class EventBreakoutTrailer:
    def __init__(self, router, interval_sec: float | None = None) -> None:
        self.router = router
        self.interval = float(
            os.getenv("EVENT_BREAKOUT_TRAIL_INTERVAL_SEC", str(interval_sec or 2))
        )
        self.log = logging.getLogger("engine.event_breakout.trailer")
        self._tracked: Set[str] = set()  # symbols (BASEQUOTE)
        self._last_stop: Dict[str, float] = {}
        try:
            from engine import metrics as MET

            self._MET = MET
        except Exception:
            self._MET = None

    async def run(self) -> None:
        # Subscribe to open events to add symbols
        try:
            from engine.core.event_bus import BUS

            BUS.subscribe("strategy.event_breakout_open", self._on_open)
        except Exception:
            pass
        while True:
            try:
                await self._tick()
            except Exception as e:
                self.log.warning("[EVENT-BO:TRAIL] tick error: %s", e)
            await asyncio.sleep(self.interval)

    async def _on_open(self, evt: Dict) -> None:
        sym = (evt.get("symbol") or "").upper()
        if sym:
            self._tracked.add(sym)
            # update gauge
            if getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_open_positions.set(len(self._tracked))
                except Exception:
                    pass

    async def _tick(self) -> None:
        # Work on a snapshot to avoid mutation during iteration
        tracked = list(self._tracked)
        for sym in tracked:
            qty = self._position_qty(sym)
            if qty <= 0:
                # position closed -> untrack
                self._tracked.discard(sym)
                self._last_stop.pop(sym, None)
                if getattr(self, "_MET", None) is not None:
                    try:
                        self._MET.event_bo_open_positions.set(len(self._tracked))
                        self._MET.event_bo_trail_exits_total.labels(symbol=sym).inc()
                    except Exception:
                        pass
                continue
            last = await self._last_price(sym)
            if not last:
                continue
            atr = await self._atr(sym)
            trail_dist = float(
                os.getenv("EVENT_BREAKOUT_TRAIL_ATR_MULT", "1.2")
            ) * float(atr)
            desired = max(self._last_stop.get(sym, 0.0), last - max(trail_dist, 0.0))
            # Round
            try:
                desired = self.router.round_tick(f"{sym}.BINANCE", desired)
            except Exception:
                pass
            # Only tighten
            if desired <= (self._last_stop.get(sym, 0.0) or 0.0):
                continue
            await self.router.amend_stop_reduce_only(
                f"{sym}.BINANCE", "SELL", float(desired), float(abs(qty))
            )
            self._last_stop[sym] = float(desired)
            if getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_trail_updates_total.labels(symbol=sym).inc()
                except Exception:
                    pass
            # Publish rollup event for digest
            try:
                from engine.core.event_bus import BUS

                await BUS.publish("event_bo.trail", {"symbol": sym})
            except Exception:
                pass

    def _position_qty(self, sym: str) -> float:
        try:
            state = self.router.portfolio_service().state
            pos = state.positions.get(sym) or state.positions.get(sym.split(".")[0])
            if pos is None:
                # Also try without venue prefix in keys
                pos = state.positions.get(sym)
            if pos is None:
                return 0.0
            return float(getattr(pos, "quantity", 0.0) or 0.0)
        except Exception:
            return 0.0

    async def _last_price(self, sym: str) -> float | None:
        try:
            px = await self.router.get_last_price(f"{sym}.BINANCE")
            return float(px) if px else None
        except Exception:
            return None

    async def _atr(self, sym: str) -> float:
        # Simple ATR via exchange klines; fallback to 0
        try:
            client = self.router.exchange_client()
            if client is None or not hasattr(client, "klines"):
                return 0.0
            kl = client.klines(
                sym,
                interval=os.getenv("EVENT_BREAKOUT_ATR_TF", "1m"),
                limit=max(int(float(os.getenv("EVENT_BREAKOUT_ATR_N", "14"))) + 1, 15),
            )
            if hasattr(kl, "__await__"):
                kl = await kl
            if not isinstance(kl, list) or len(kl) < 2:
                return 0.0
            prev_close = None
            trs = []
            n = int(float(os.getenv("EVENT_BREAKOUT_ATR_N", "14")))
            for row in kl[-(n + 1) :]:
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])
                if prev_close is None:
                    tr = high - low
                else:
                    tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
                prev_close = close
            if len(trs) <= 1:
                return 0.0
            trs = trs[1:]
            return sum(trs) / len(trs)
        except Exception:
            return 0.0
