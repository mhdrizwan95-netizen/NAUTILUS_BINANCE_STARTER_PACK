from __future__ import annotations

import logging
import os
import time
from typing import Any


def _as_bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() not in {"0", "false", "no"}


def _log_suppressed(context: str, exc: Exception) -> None:
    logging.getLogger("engine.depeg_guard").debug(
        "%s suppressed exception: %s", context, exc, exc_info=True
    )


_DEPEG_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    ValueError,
    ConnectionError,
    KeyError,
    TypeError,
)


class DepegGuard:
    def __init__(
        self, router, md=None, bus=None, clock=time, log: logging.Logger | None = None
    ) -> None:
        self.router = router
        self.md = md
        self.bus = bus
        self.clock = clock
        self.log = log or logging.getLogger("engine.depeg_guard")
        # Config
        self.enabled = _as_bool(os.getenv("DEPEG_GUARD_ENABLED"), False)
        self.threshold_pct = float(os.getenv("DEPEG_THRESHOLD_PCT", "0.5"))
        self.confirm_windows = int(float(os.getenv("DEPEG_CONFIRM_WINDOWS", "3")))
        self.cooldown_min = int(float(os.getenv("DEPEG_ACTION_COOLDOWN_MIN", "120")))
        self.exit_risk = _as_bool(os.getenv("DEPEG_EXIT_RISK"), False)
        self.switch_quote = _as_bool(os.getenv("DEPEG_SWITCH_QUOTE"), False)
        self.watch_symbols = [
            s.strip().upper()
            for s in os.getenv("DEPEG_WATCH_SYMBOLS", "USDTUSDC,BTCUSDT,BTCUSDC").split(",")
            if s.strip()
        ]
        # State
        self.confirm = 0
        self.safe_until = 0.0

    def _last(self, symbol: str) -> float:
        try:
            if self.md and hasattr(self.md, "last"):
                px = self.md.last(symbol)
                return float(px) if px else 0.0
        except _DEPEG_ERRORS as exc:
            _log_suppressed("depeg_guard.last.md", exc)
        try:
            # Fallback to router price
            px = self.router.get_last_price(f"{symbol}.BINANCE")
            if hasattr(px, "__await__"):
                import asyncio

                loop = asyncio.get_event_loop()
                px = loop.run_until_complete(px)  # in case called sync
            return float(px) if px else 0.0
        except _DEPEG_ERRORS as exc:
            _log_suppressed("depeg_guard.last.router", exc)
            return 0.0

    def _peg_deviation(self) -> float:
        # Estimate via direct USDT/USDC and BTC leg parity
        devs: list[float] = []
        try:
            if "USDTUSDC" in self.watch_symbols:
                usdt_usdc = self._last("USDTUSDC")
                if usdt_usdc:
                    devs.append(abs(usdt_usdc - 1.0) * 100.0)
        except _DEPEG_ERRORS as exc:
            _log_suppressed("depeg_guard.dev.usdt_usdc", exc)
        try:
            if "BTCUSDT" in self.watch_symbols and "BTCUSDC" in self.watch_symbols:
                btc_usdt = self._last("BTCUSDT")
                btc_usdc = self._last("BTCUSDC")
                if btc_usdt and btc_usdc:
                    implied = btc_usdt / btc_usdc
                    devs.append(abs(implied - 1.0) * 100.0)
        except _DEPEG_ERRORS as exc:
            _log_suppressed("depeg_guard.dev.btc_pairs", exc)
        return max(devs) if devs else 0.0

    async def tick(self) -> None:
        if not self.enabled:
            return
        now = float(self.clock.time())
        if now < self.safe_until:
            return
        dev = self._peg_deviation()
        if dev >= float(self.threshold_pct):
            self.confirm += 1
        else:
            self.confirm = 0
        if self.confirm >= int(self.confirm_windows):
            self.safe_until = now + 60.0 * float(self.cooldown_min)
            try:
                if self.bus is not None:
                    self.bus.fire("risk.depeg_trigger", {"deviation_pct": dev})
                    self.bus.fire("health.state", {"state": 2, "reason": "depeg_trigger"})
            except _DEPEG_ERRORS as exc:
                _log_suppressed("depeg_guard.bus_fire", exc)
            await self._apply_actions(dev)

    async def _apply_actions(self, dev: float) -> None:
        self.log.warning("[DEPEG] Triggered at %.2f%%", dev)
        # Halt new entries via trading flag
        try:
            if hasattr(self.router, "set_trading_enabled"):
                await self._maybe_await(self.router.set_trading_enabled(False))
        except _DEPEG_ERRORS as exc:
            _log_suppressed("depeg_guard.disable_trading", exc)
        if self.exit_risk:
            # Best-effort flatten
            positions = []
            try:
                if hasattr(self.router, "list_positions"):
                    positions = await self._maybe_await(self.router.list_positions())
            except _DEPEG_ERRORS as exc:
                _log_suppressed("depeg_guard.list_positions", exc)
                positions = []
            for p in positions or []:
                try:
                    sym = p.get("symbol") if isinstance(p, dict) else getattr(p, "symbol", "")
                    qty = float(
                        p.get("qty") if isinstance(p, dict) else getattr(p, "quantity", 0.0)
                    )
                    if not sym or qty == 0:
                        continue
                    side = "SELL" if qty > 0 else "BUY"
                    await self._maybe_await(
                        self.router.place_reduce_only_market(sym, side, abs(qty))
                    )
                except _DEPEG_ERRORS as exc:
                    self.log.warning("[DEPEG] exit fail %s: %s", getattr(p, "symbol", "?"), exc)
        if self.switch_quote:
            try:
                if hasattr(self.router, "set_preferred_quote"):
                    self.router.set_preferred_quote("USDC")
            except _DEPEG_ERRORS as exc:
                _log_suppressed("depeg_guard.switch_quote", exc)

    async def _maybe_await(self, res: Any) -> Any:
        if hasattr(res, "__await__"):
            return await res
        return res
