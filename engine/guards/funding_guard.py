from __future__ import annotations

import logging
import os
from typing import Any


def _as_bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() not in {"0", "false", "no"}


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger("engine.funding_guard").debug(
        "%s suppressed exception: %s", context, exc, exc_info=True
    )


_FUNDING_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    ValueError,
    ConnectionError,
    KeyError,
    TypeError,
)


class FundingGuard:
    def __init__(self, router, bus=None, log: logging.Logger | None = None) -> None:
        self.router = router
        self.bus = bus
        self.log = log or logging.getLogger("engine.funding_guard")
        self.enabled = _as_bool(os.getenv("FUNDING_GUARD_ENABLED"), False)
        self.spike_threshold = float(os.getenv("FUNDING_SPIKE_THRESHOLD", "0.15")) / 100.0
        self.trim_pct = float(os.getenv("FUNDING_TRIM_PCT", "0.30"))
        self.hedge_ratio = float(os.getenv("FUNDING_HEDGE_RATIO", "0.00"))

    async def tick(self) -> None:
        if not self.enabled:
            return
        client = self.router.exchange_client()
        if client is None or not hasattr(client, "bulk_premium_index"):
            return
        try:
            data = client.bulk_premium_index()
            if hasattr(data, "__await__"):
                data = await data
            # Expect mapping symbol->dict with lastFundingRate or estimatedRate
            for sym, obj in (data or {}).items():
                try:
                    rate = float(obj.get("lastFundingRate") or obj.get("estimatedRate") or 0.0)
                except _FUNDING_ERRORS as exc:
                    _log_suppressed("funding_guard.rate_parse", exc)
                    rate = 0.0
                if abs(rate) >= self.spike_threshold:
                    try:
                        if self.bus is not None:
                            self.bus.fire("risk.funding_spike", {"symbol": sym, "rate": rate})
                    except _FUNDING_ERRORS as exc:
                        _log_suppressed("funding_guard.bus_fire", exc)
                    await self._mitigate(sym, rate)
        except _FUNDING_ERRORS as exc:
            _log_suppressed("funding_guard.bulk_fetch", exc)
            return

    async def _mitigate(self, sym: str, rate: float) -> None:
        pos = None
        try:
            # Try to get position from portfolio state
            state = self.router.portfolio_service().state
            pos = state.positions.get(sym) or state.positions.get(sym.split(".")[0])
        except _FUNDING_ERRORS as exc:
            _log_suppressed("funding_guard.lookup_position", exc)
            pos = None
        if pos is None:
            return
        qty = float(getattr(pos, "quantity", 0.0) or 0.0)
        if qty == 0.0:
            return
        # paying if long with +rate or short with -rate
        paying = (qty > 0 and rate > 0) or (qty < 0 and rate < 0)
        if not paying:
            return
        cut_qty = abs(qty) * float(self.trim_pct)
        if cut_qty > 0:
            side = "SELL" if qty > 0 else "BUY"
            await self.router.place_reduce_only_market(
                f"{sym}.BINANCE" if "." not in sym else sym, side, cut_qty
            )
            self.log.info(
                "[FUNDING] Trimmed %s by %.2f%% for rate %.4f%%",
                sym,
                self.trim_pct * 100.0,
                rate * 100.0,
            )
        if self.hedge_ratio > 0:
            try:
                await self._maybe_await(self.router.auto_net_hedge_btc(percent=self.hedge_ratio))
            except _FUNDING_ERRORS as exc:
                _log_suppressed("funding_guard.auto_hedge", exc)

    async def _maybe_await(self, res: Any) -> Any:
        if hasattr(res, "__await__"):
            return await res
        return res
