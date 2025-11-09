"""Simple 15-minute momentum breakout strategy for Kraken."""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass

from engine.config.defaults import MOMENTUM_15M_DEFAULTS
from engine.config.env import env_bool, env_float, env_int, env_str
from engine.execution.execute import StrategyExecutor

logger = logging.getLogger("engine.momentum.15m")
_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)
_EXECUTION_ERRORS = _SUPPRESSIBLE_EXCEPTIONS


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


@dataclass(frozen=True)
class Momentum15mConfig:
    enabled: bool
    dry_run: bool
    symbol: str
    lookback_ticks: int
    quantity: float
    allow_shorts: bool
    rearm_sec: float


def load_momentum_15m_config() -> Momentum15mConfig:
    symbol_raw = (
        env_str("MOMENTUM_15M_SYMBOL", MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_SYMBOL"]).strip().upper()
    )
    if not symbol_raw:
        symbol_raw = MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_SYMBOL"]
    return Momentum15mConfig(
        enabled=env_bool("MOMENTUM_15M_ENABLED", MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_ENABLED"]),
        dry_run=env_bool("MOMENTUM_15M_DRY_RUN", MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_DRY_RUN"]),
        symbol=symbol_raw,
        lookback_ticks=max(
            5,
            env_int(
                "MOMENTUM_15M_LOOKBACK_TICKS",
                MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_LOOKBACK_TICKS"],
            ),
        ),
        quantity=max(
            0.0,
            env_float("MOMENTUM_15M_QUANTITY", MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_QUANTITY"]),
        ),
        allow_shorts=env_bool(
            "MOMENTUM_15M_ALLOW_SHORTS",
            MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_ALLOW_SHORTS"],
        ),
        rearm_sec=max(
            0.0,
            env_float(
                "MOMENTUM_15M_REARM_SEC",
                MOMENTUM_15M_DEFAULTS["MOMENTUM_15M_REARM_SEC"],
            ),
        ),
    )


class Momentum15mStrategy:
    """Naive 15-minute momentum breakout strategy that interacts via StrategyExecutor."""

    def __init__(self, router, risk, cfg: Momentum15mConfig | None = None, *, clock=time) -> None:
        self.cfg = cfg or load_momentum_15m_config()
        self._router = router
        self._clock = clock
        symbol = self.cfg.symbol
        if "." not in symbol:
            symbol = f"{symbol}.KRAKEN"
        self.symbol = symbol.upper()
        self._base = self.symbol.split(".")[0]
        self._venue = self.symbol.split(".")[1]
        lookback = max(3, int(self.cfg.lookback_ticks))
        self._window: deque[float] = deque(maxlen=lookback)
        self._executor = StrategyExecutor(
            risk=risk,
            router=router,
            default_dry_run=self.cfg.dry_run,
            source="momentum_15m",
        )
        self._last_signal_ts: float = 0.0

    def _position_quantity(self) -> float:
        try:
            portfolio = self._router.portfolio_service()
            positions = getattr(portfolio.state, "positions", {})
            pos = positions.get(self._base)
            if pos is None:
                return 0.0
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
        except _SUPPRESSIBLE_EXCEPTIONS:
            return 0.0
        else:
            return qty

    def on_tick(self, symbol: str, price: float, ts: float) -> None:
        if not self.cfg.enabled:
            return
        if price is None or price <= 0 or not math.isfinite(price):
            return
        if not symbol:
            return

        base = symbol.split(".")[0].upper()
        if base != self._base:
            return

        now = ts if ts is not None else self._clock.time()
        self._window.append(float(price))
        window_maxlen = self._window.maxlen or 0
        if window_maxlen <= 0 or len(self._window) < window_maxlen:
            return

        window_high = max(self._window)
        window_low = min(self._window)
        if not math.isfinite(window_high) or not math.isfinite(window_low):
            return

        position_qty = self._position_quantity()
        in_position = position_qty > 0.0

        side: str | None = None
        qty: float = 0.0
        meta_reason = ""

        if not in_position and price >= window_high:
            side = "BUY"
            qty = float(self.cfg.quantity or 0.0)
            if qty <= 0.0:
                return
            meta_reason = "breakout_high"
        elif in_position and price <= window_low:
            side = "SELL"
            qty = float(position_qty)
            if qty <= 0.0:
                return
            meta_reason = "breakdown_low"
        elif in_position and self.cfg.allow_shorts and price <= window_low:
            side = "SELL"
            qty = float(self.cfg.quantity or 0.0)
            if qty <= 0.0:
                qty = float(position_qty)
            meta_reason = "short_breakdown"

        if side is None or qty <= 0.0:
            return

        if self.cfg.rearm_sec > 0 and (now - self._last_signal_ts) < self.cfg.rearm_sec:
            return

        meta = {
            "window_high": window_high,
            "window_low": window_low,
            "reason": meta_reason,
        }
        signal = {
            "strategy": "momentum_15m",
            "symbol": self.symbol,
            "side": side,
            "quantity": qty,
            "quote": None,
            "meta": meta,
            "tag": "momentum_15m",
            "ts": now,
        }

        try:
            result = self._executor.execute_sync(signal)
            status = result.get("status")
            if status not in {"submitted", "dry_run", "backtest"}:
                logger.info(
                    "[MOMO15] order skipped status=%s team=%s",
                    status,
                    result.get("error") or result.get("message"),
                )
            else:
                self._last_signal_ts = now
        except _EXECUTION_ERRORS as exc:
            _log_suppressed("momentum_15m.execute", exc)


__all__ = [
    "Momentum15mConfig",
    "Momentum15mStrategy",
    "load_momentum_15m_config",
]
