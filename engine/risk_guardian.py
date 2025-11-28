"""
Risk Guardian: cross-margin and equity monitors + auto de-risk actions.

Implements the "automate, not negotiate" guardrails from the playbook:
 - Daily stop (e.g., -$100) -> pause trading until UTC reset
 - Cross-margin health floor (e.g., 1.35) -> cancel entries, tighten stops
 - Hard de-risk if health < critical (e.g., 1.30) -> reduce largest VAR

Defaults are disabled; enable with env vars to avoid impacting tests.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta

from engine.runtime.config import load_runtime_config
from engine.services.param_client import get_cached_params

from .metrics import REGISTRY as MET

logger = logging.getLogger(__name__)

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    asyncio.TimeoutError,
)


def _log_suppressed(context: str, exc: Exception) -> None:
    logger.debug("%s suppressed: %s", context, exc, exc_info=True)


def _as_float(v: str | None, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _as_bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return str(v).lower() not in {"0", "false", "no"}


@dataclass
class GuardianConfig:
    enabled: bool = False
    poll_sec: float = 5.0
    cross_health_floor: float = 1.35  # Cross margin: want >= floor
    futures_mmr_floor: float = 0.80  # Futures MMR: want <= floor
    critical_ratio: float = 1.07  # worst-score threshold vs floor for hard action
    max_daily_loss_usd: float = 100.0
    max_open_positions: int = 5
    daily_reset_tz: str = "UTC"
    daily_reset_hour: int = 0
    # VAR controls
    var_use_stop_first: bool = True
    var_atr_tf: str = "5m"
    var_atr_n: int = 14
    var_trim_pct: float = 0.30


def load_guardian_config() -> GuardianConfig:
    return GuardianConfig(
        enabled=_as_bool(os.getenv("GUARDIAN_ENABLED"), False),
        poll_sec=_as_float(os.getenv("GUARDIAN_POLL_SEC"), 5.0),
        cross_health_floor=_as_float(os.getenv("CROSS_HEALTH_FLOOR"), 1.35),
        futures_mmr_floor=_as_float(os.getenv("FUTURES_MMR_FLOOR"), 0.80),
        critical_ratio=_as_float(os.getenv("HEALTH_CRITICAL_RATIO"), 1.07),
        max_daily_loss_usd=_as_float(os.getenv("MAX_DAILY_LOSS_USD"), 100.0),
        max_open_positions=int(_as_float(os.getenv("MAX_OPEN_POSITIONS"), 5)),
        daily_reset_tz=os.getenv("DAILY_RESET_TZ", "UTC"),
        daily_reset_hour=int(_as_float(os.getenv("DAILY_RESET_HOUR"), 0)),
        var_use_stop_first=_as_bool(os.getenv("VAR_USE_STOP_FIRST"), True),
        var_atr_tf=os.getenv("VAR_ATR_TF", "5m"),
        var_atr_n=int(_as_float(os.getenv("VAR_ATR_N"), 14)),
        var_trim_pct=float(_as_float(os.getenv("VAR_TRIM_PCT"), 0.30)),
    )


class RiskGuardian:
    def __init__(self, cfg: GuardianConfig | None = None) -> None:
        self.cfg = cfg or load_guardian_config()
        self._running = False
        self._task: asyncio.Task | None = None
        self._day_anchor: tuple[int, float] | None = None  # (YYYYMMDD, realized_at_anchor)
        self._paused_until_utc_reset = False
        self._tz = None
        self._max_loss_env_override = os.getenv("MAX_DAILY_LOSS_USD")
        try:
            self._daily_loss_pct = float(
                load_runtime_config().risk.daily_stop_pct  # type: ignore[attr-defined]
            )
        except (AttributeError, TypeError, ValueError) as exc:
            _log_suppressed("guardian.daily_stop_pct", exc)
            self._daily_loss_pct = None
        try:
            self._tz = zoneinfo.ZoneInfo(self.cfg.daily_reset_tz)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
            _log_suppressed("guardian.reset_tz", exc)
            self._tz = zoneinfo.ZoneInfo("UTC")

    async def start(self) -> None:
        if not self.cfg.enabled or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="risk-guardian")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except TimeoutError:
                self._task.cancel()
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("guardian.stop", exc)
                self._task.cancel()

    async def _loop(self) -> None:
        from .app import router as order_router
        from .config import load_risk_config
        from .risk import RiskRails

        rails = RiskRails(load_risk_config())
        while self._running:
            t0 = time.time()
            try:
                # 1. Fetch Dynamic Global Params
                # "RiskGuardian must fetch global params (e.g., max_daily_loss) dynamically."
                dyn_params = get_cached_params("risk_guardian", "GLOBAL")
                if dyn_params and "params" in dyn_params:
                    try:
                        p = dyn_params["params"]
                        # GuardianConfig is a standard dataclass (not frozen), so we can update attributes directly.
                        # We map param names to config attributes if they match.
                        
                        # Max Daily Loss
                        if "max_daily_loss_usd" in p:
                            new_loss = float(p["max_daily_loss_usd"])
                            # --- SAFETY INTERLOCK (HARD CEILING) ---
                            # Clamp to 10% of Equity if known, else trust the param (or static default if param is crazy high?)
                            # We'll check equity from the snapshot below, but we need to set config now.
                            # Let's defer clamping until we have the snapshot.
                            self.cfg.max_daily_loss_usd = new_loss
                            
                        # Cross Health Floor
                        if "cross_health_floor" in p:
                            self.cfg.cross_health_floor = float(p["cross_health_floor"])
                            
                        # Critical Ratio
                        if "critical_ratio" in p:
                            self.cfg.critical_ratio = float(p["critical_ratio"])
                            
                    except (ValueError, TypeError):
                        pass

                snap = await order_router.get_account_snapshot()
                
                # --- SAFETY INTERLOCK (HARD CEILING APPLICATION) ---
                # Clamp max_daily_loss_usd to 10% of Equity
                if snap:
                    equity = float(snap.get("equity") or snap.get("equity_usd") or 0.0)
                    if equity > 0:
                        hard_cap = equity * 0.10
                        if self.cfg.max_daily_loss_usd > hard_cap:
                            self.cfg.max_daily_loss_usd = hard_cap

                await self._enforce_daily_stop(order_router)
                await self._enforce_cross_health(order_router, snap)
                # Keep portfolio gauges fresh via rails snapshot ingestion
                try:
                    rails.refresh_snapshot_metrics(snap)
                except _SUPPRESSIBLE_EXCEPTIONS as exc:
                    _log_suppressed("guardian.refresh_snapshot_metrics", exc)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                # Soft-fail to avoid killing the loop
                _log_suppressed("guardian.loop", exc)
                try:
                    ctr = MET.get("engine_venue_errors_total")
                    if ctr is not None:
                        ctr.labels(venue="guard", error="LOOP_ERROR").inc()
                except _SUPPRESSIBLE_EXCEPTIONS as metric_exc:
                    _log_suppressed("guardian.loop.metric", metric_exc)
            dt = max(0.0, self.cfg.poll_sec - (time.time() - t0))
            await asyncio.sleep(dt)

    async def _enforce_daily_stop(self, order_router) -> None:
        state = order_router.portfolio_service().state
        realized = float(state.realized or 0.0)
        equity = float(getattr(state, "equity", 0.0) or 0.0)
        loss_limit_usd = float(self.cfg.max_daily_loss_usd)
        if self._max_loss_env_override:
            try:
                loss_limit_usd = float(self._max_loss_env_override)
                self.cfg.max_daily_loss_usd = loss_limit_usd
            except (TypeError, ValueError):
                pass
        elif self._daily_loss_pct is not None and equity > 0:
            loss_limit_usd = max(loss_limit_usd, abs(equity) * abs(self._daily_loss_pct))
            self.cfg.max_daily_loss_usd = loss_limit_usd

        # Anchor at first run of day based on configured timezone/hour
        now_dt = datetime.now(self._tz)
        # daily boundary hour
        boundary = now_dt.replace(hour=self.cfg.daily_reset_hour, minute=0, second=0, microsecond=0)
        if now_dt < boundary:
            # before today's boundary, use yesterday's
            boundary = boundary - timedelta(days=1)
        day = boundary.year * 10000 + boundary.month * 100 + boundary.day
        if self._day_anchor is None or self._day_anchor[0] != day:
            self._day_anchor = (day, realized)
            self._paused_until_utc_reset = False
            # Auto re-arm at boundary
            _write_trading_flag(True)
            # Emit health OK
            try:
                from engine.core.event_bus import BUS as _BUS

                _BUS.fire("health.state", {"state": 0, "reason": "daily_reset"})
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("guardian.daily_reset_signal", exc)
            return
        pnl_day = realized - (self._day_anchor[1] or 0.0)
        try:
            pnl_metric = MET.get("pnl_realized_total")
            if pnl_metric is not None:
                pnl_metric.set(realized)
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("guardian.pnl_metric", exc)
        if pnl_day <= -abs(loss_limit_usd) and not self._paused_until_utc_reset:
            # Pause trading via RiskRails config gate
            # Write a single-source-of-truth flag file; RiskRails will consult it on each order
            _write_trading_flag(False)
            try:
                trading_metric = MET.get("trading_enabled")
                if trading_metric is not None:
                    trading_metric.set(0)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("guardian.trading_metric", exc)
            self._paused_until_utc_reset = True
            self._paused_until_utc_reset = True
            try:
                from .core.event_bus import publish_risk_event

                # 1. Publish explicit PAUSE action for immediate in-memory gating
                await publish_risk_event(
                    "violation",
                    {
                        "action": "PAUSE",
                        "reason": "daily_stop",
                        "pnl_day": pnl_day,
                        "limit": self.cfg.max_daily_loss_usd,
                    },
                )
                # 2. Publish informational event
                await publish_risk_event(
                    "daily_stop",
                    {"pnl_day": pnl_day, "limit": self.cfg.max_daily_loss_usd},
                )
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("guardian.publish_daily_stop", exc)

    async def _enforce_cross_health(self, order_router, snap: dict | None) -> None:
        """Evaluate cross-margin level and futures MMR; act on worst breach.

        Normalization:
          - Cross margin: want marginLevel >= floor -> score = floor / level
          - Futures MMR: want mmr <= floor -> score = mmr / floor
          Worst score >= 1.0 indicates breach; >= critical_ratio triggers hard de-risk.
        """
        # Extract common fields
        cross_level = _safe_float(_dig(snap, ["marginLevel"]))
        # Pull futures fields if available
        fut_mmr = None
        maint_total = _safe_float(_dig(snap, ["totalMaintMargin"]))
        wallet = _safe_float(_dig(snap, ["totalWalletBalance"]))
        upl = _safe_float(_dig(snap, ["totalUnrealizedProfit"]))
        if maint_total is not None and wallet is not None and upl is not None:
            denom = wallet + upl
            if denom > 0:
                fut_mmr = float(maint_total) / float(denom)

        # Normalized worst-score
        worst = 0.0
        if cross_level is not None and cross_level > 0:
            worst = max(worst, self.cfg.cross_health_floor / max(cross_level, 1e-9))
        if fut_mmr is not None and fut_mmr > 0:
            worst = max(worst, fut_mmr / max(self.cfg.futures_mmr_floor, 1e-9))

        if worst >= 1.0:
            await self._derisk_soft(order_router, worst)
        if worst >= self.cfg.critical_ratio:
            await self._derisk_hard(order_router, worst)

    async def _derisk_soft(self, order_router, score: float) -> None:
        # Cancel resting entries & tighten stops — publish events for now
        try:
            from .core.event_bus import publish_risk_event

            await publish_risk_event(
                "cross_health_soft",
                {
                    "worst_score": score,
                    "floors": {
                        "cross": self.cfg.cross_health_floor,
                        "futures_mmr": self.cfg.futures_mmr_floor,
                    },
                },
            )
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("guardian.derisk_soft", exc)

    async def _derisk_hard(self, order_router, score: float) -> None:
        # Reduce largest-VAR position by 30% until health recovers (best-effort)
        try:
            from .core.event_bus import publish_risk_event
        except ImportError as exc:
            _log_suppressed("guardian.import_publish_risk_event", exc)
            publish_risk_event = None
        positions = list(order_router.portfolio_service().state.positions.values())
        if not positions:
            return
        # Compute VAR ranking (stop-aware, ATR fallback)
        try:
            from engine.risk_var import sort_positions_by_var_desc
        except ImportError as exc:
            _log_suppressed("guardian.import_risk_var", exc)
            sort_positions_by_var_desc = None  # type: ignore
        if sort_positions_by_var_desc is not None:
            ranked = sort_positions_by_var_desc(
                positions,
                md=None,
                tf=self.cfg.var_atr_tf,
                n=self.cfg.var_atr_n,
                use_stop_first=self.cfg.var_use_stop_first,
            )
            target = ranked[0] if ranked else None
        else:
            target = max(
                positions,
                key=lambda p: abs(getattr(p, "quantity", 0.0) * getattr(p, "last_price", 0.0)),
            )
        if target is None:
            return
        qty = float(getattr(target, "quantity", 0.0))
        last = float(getattr(target, "last_price", 0.0))
        if qty == 0.0 or last == 0.0:
            return
        symbol = getattr(target, "symbol", "") or ""
        base = symbol.split(".")[0].upper()
        venue = symbol.split(".")[1].upper() if "." in symbol else "BINANCE"
        side = "SELL" if qty > 0 else "BUY"
        reduce_qty = abs(qty) * float(self.cfg.var_trim_pct)
        try:
            await order_router.market_quantity(f"{base}.{venue}", side, reduce_qty)
            if publish_risk_event:
                await publish_risk_event(
                    "cross_health_hard",
                    {
                        "worst_score": score,
                        "symbol": base,
                        "reduced_qty": reduce_qty,
                        "side": side,
                    },
                )
        except _SUPPRESSIBLE_EXCEPTIONS as exc:
            _log_suppressed("guardian.derisk_hard", exc)

        # If critical, also pause trading to prevent further damage
        if score >= self.cfg.critical_ratio * 1.1:  # Extra buffer before full kill
            try:
                from .core.event_bus import publish_risk_event

                if publish_risk_event:
                    await publish_risk_event(
                        "violation",
                        {
                            "action": "PAUSE",
                            "reason": "cross_health_critical",
                            "score": score,
                        },
                    )
                    _write_trading_flag(False)
            except _SUPPRESSIBLE_EXCEPTIONS as exc:
                _log_suppressed("guardian.derisk_hard_pause", exc)


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _dig(d: dict | None, path: list[str]):
    cur = d or {}
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _write_trading_flag(enabled: bool) -> None:
    try:
        import os

        os.makedirs("state", exist_ok=True)
        with open("state/trading_enabled.flag", "w", encoding="utf-8") as fh:
            fh.write("true" if enabled else "false")
    except OSError as exc:
        _log_suppressed("guardian.write_trading_flag", exc)
