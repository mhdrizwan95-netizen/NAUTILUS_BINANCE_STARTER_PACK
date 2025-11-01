from __future__ import annotations

import logging
import os
from typing import Any


class BracketGovernor:
    """Simple TP/SL governance wired off trade.fill events.

    - Places a reduce-only limit TP and a reduce-only stop on each fill.
    - Percentages are read from env: TP_BPS, SL_BPS (basis points).
    - Enable with BRACKET_GOVERNOR_ENABLED=true (default true).
    - Stop amend obeys ALLOW_STOP_AMEND; set it true to actually place stops.
    """

    def __init__(self, router, bus, log: logging.Logger | None = None) -> None:
        self.router = router
        self.bus = bus
        self.log = log or logging.getLogger("governance.bracket")
        # Read bps once on startup; can be made dynamic later
        try:
            self.tp_bps = float(os.getenv("TP_BPS", "20.0"))  # 20 bps = 0.20%
        except Exception:
            self.tp_bps = 20.0
        try:
            self.sl_bps = float(os.getenv("SL_BPS", "30.0"))
        except Exception:
            self.sl_bps = 30.0

    def wire(self) -> None:
        try:
            self.bus.subscribe("trade.fill", self._on_fill)
            self.log.info(
                "BracketGovernor wired (TP_BPS=%.2f, SL_BPS=%.2f)",
                self.tp_bps,
                self.sl_bps,
            )
        except Exception:
            self.log.warning("BracketGovernor failed to wire", exc_info=True)

    async def _on_fill(self, evt: dict[str, Any]) -> None:
        try:
            symbol = (evt.get("symbol") or "").upper()
            side = str(evt.get("side") or "").upper()
            avg = float(evt.get("avg_price") or 0.0)
            qty = float(evt.get("filled_qty") or 0.0)
            if not symbol or avg <= 0.0 or qty <= 0.0 or side not in {"BUY", "SELL"}:
                return

            tp_mult = 1.0 + (self.tp_bps / 10_000.0)
            sl_mult = 1.0 - (self.sl_bps / 10_000.0)
            tp_px = avg * (tp_mult if side == "BUY" else (2.0 - tp_mult))
            sl_px = avg * (sl_mult if side == "BUY" else (2.0 - sl_mult))

            qual = f"{symbol}.BINANCE" if "." not in symbol else symbol

            # Place TP reduce-only limit (best-effort)
            try:
                await self.router.place_reduce_only_limit(
                    qual, "SELL" if side == "BUY" else "BUY", abs(qty), float(tp_px)
                )
            except Exception:
                pass

            # Place/Amend SL reduce-only stop (obeys ALLOW_STOP_AMEND)
            try:
                await self.router.amend_stop_reduce_only(
                    qual, "SELL" if side == "BUY" else "BUY", float(sl_px), abs(qty)
                )
            except Exception:
                pass

            try:
                self.log.info(
                    "[BRACKET] %s side=%s qty=%.8f avg=%.6f TP=%.6f SL=%.6f",
                    symbol,
                    side,
                    qty,
                    avg,
                    tp_px,
                    sl_px,
                )
            except Exception:
                pass
        except Exception:
            # Never break event loop
            try:
                self.log.warning("BracketGovernor on_fill error", exc_info=True)
            except Exception:
                pass
