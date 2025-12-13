from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from engine.core.market_resolver import resolve_market_choice

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
)


@dataclass
class BreakoutConfig:
    enabled: bool = False
    dry_run: bool = True
    half_size_minutes: int = 5
    base_risk_usd: float = 40.0
    size_usd: float = 120.0
    prefer_futures: bool = True
    default_market: str = "futures"
    leverage_major: int = 3
    leverage_default: int = 2
    sl_method: str = "min3low_or_atr"
    atr_tf: str = "1m"
    atr_n: int = 14
    tp1_pct: float = 0.03
    tp1_portion: float = 0.33
    tp2_pct: float = 0.06
    tp2_portion: float = 0.33
    trail_atr_mult: float = 1.2
    cooldown_minutes: int = 15
    max_spread_pct: float = 0.006
    late_chase_pct_30m: float = 0.20
    min_notional_1m_usd: float = 500_000.0
    metrics_enabled: bool = False
    denylist_enabled: bool = False
    denylist_path: str = "conf/event_denylist.txt"


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() not in {"0", "false", "no"}


def load_breakout_config() -> BreakoutConfig:
    prefer_futures = _env_bool("EVENT_BREAKOUT_PREFER_FUTURES", True)
    default_market_raw = os.getenv("EVENT_BREAKOUT_DEFAULT_MARKET", "").strip().lower()
    default_market = default_market_raw or ("futures" if prefer_futures else "spot")
    if default_market not in {"spot", "margin", "futures", "options"}:
        default_market = "futures" if prefer_futures else "spot"
    return BreakoutConfig(
        enabled=_env_bool("EVENT_BREAKOUT_ENABLED", False),
        dry_run=_env_bool("EVENT_BREAKOUT_DRY_RUN", True),
        half_size_minutes=int(float(os.getenv("EVENT_BREAKOUT_HALF_SIZE_MINUTES", "5"))),
        base_risk_usd=float(os.getenv("EVENT_BREAKOUT_BASE_RISK_USD", "40")),
        size_usd=float(os.getenv("EVENT_BREAKOUT_SIZE_USD", "120")),
        prefer_futures=prefer_futures,
        default_market=default_market,
        leverage_major=int(float(os.getenv("EVENT_BREAKOUT_LEV_MAJOR", "3"))),
        leverage_default=int(float(os.getenv("EVENT_BREAKOUT_LEV_DEFAULT", "2"))),
        atr_tf=os.getenv("EVENT_BREAKOUT_ATR_TF", "1m"),
        atr_n=int(float(os.getenv("EVENT_BREAKOUT_ATR_N", "14"))),
        tp1_pct=float(os.getenv("EVENT_BREAKOUT_TP1_PCT", "0.03")),
        tp1_portion=float(os.getenv("EVENT_BREAKOUT_TP1_PORTION", "0.33")),
        tp2_pct=float(os.getenv("EVENT_BREAKOUT_TP2_PCT", "0.06")),
        tp2_portion=float(os.getenv("EVENT_BREAKOUT_TP2_PORTION", "0.33")),
        trail_atr_mult=float(os.getenv("EVENT_BREAKOUT_TRAIL_ATR_MULT", "1.2")),
        cooldown_minutes=int(float(os.getenv("EVENT_BREAKOUT_COOLDOWN_MIN", "15"))),
        max_spread_pct=float(os.getenv("EVENT_BREAKOUT_MAX_SPREAD_PCT", "0.006")),
        late_chase_pct_30m=float(os.getenv("EVENT_BREAKOUT_LATE_CHASE_PCT_30M", "0.20")),
        min_notional_1m_usd=float(os.getenv("EVENT_BREAKOUT_MIN_NOTIONAL_1M_USD", "500000")),
        metrics_enabled=_env_bool("EVENT_BREAKOUT_METRICS", False),
        denylist_enabled=_env_bool("EVENT_BREAKOUT_DENYLIST_ENABLED", False),
        denylist_path=os.getenv("EVENT_BREAKOUT_DENYLIST_PATH", "conf/event_denylist.txt"),
    )


@dataclass
class BreakoutPlan:
    symbol: str
    venue: str
    side: str
    notional_usd: float
    leverage: int
    sl_price: float
    tp1_price: float
    tp2_price: float
    trail_atr_usd: float
    half_applied: bool = False
    market: str = "futures"


class EventBreakout:
    def __init__(
        self,
        router,
        md=None,
        cfg: BreakoutConfig | None = None,
        clock=time,
        logger=None,
    ):
        self.cfg = cfg or load_breakout_config()
        self.router = router
        self.md = md  # Optional external MD adapter
        self.clock = clock
        self.log = logger or logging.getLogger("engine.event_breakout")
        self._cooldowns: dict[str, float] = {}
        try:
            from engine import metrics as MET

            self._MET = MET
        except Exception as exc:
            self._MET = None
        # Load denylist
        self.deny_enabled = bool(self.cfg.denylist_enabled)
        self.denylist = self._load_denylist(self.cfg.denylist_path)
        # Entropy-based temporary denylist
        self._entropy_enabled = bool(_env_bool("ENTROPY_DENY_ENABLED", False))
        self._entropy_reason_count = int(float(os.getenv("ENTROPY_DENY_REASON_COUNT", "3")))
        self._entropy_window = float(os.getenv("ENTROPY_DENY_WINDOW_MIN", "30")) * 60.0
        self._entropy_dur = float(os.getenv("ENTROPY_DENY_DURATION_MIN", "120")) * 60.0
        self._entropy_reasons: dict[str, dict[str, float]] = {}
        self._deny_temp: dict[str, float] = {}

    async def on_event(self, evt: dict[str, Any]):
        if not self.cfg.enabled:
            return
        sym = (evt.get("symbol") or "").upper()
        if not sym:
            return
            
        # --- Dynamic Parameter Adaptation (Universal) ---
        try:
            from engine.services.param_client import apply_dynamic_config, update_context
            update_context(sym, {"strategy": "event_breakout", "event_type": evt.get("type", "unknown")})
            apply_dynamic_config(self, sym)
        except ImportError:
            pass
        except Exception as exc:
            pass
            
        # Denylist enforcement (early exit)
        now = float(self.clock.time())
        # expire temp denies
        for k, until in list(self._deny_temp.items()):
            if now >= until:
                self._deny_temp.pop(k, None)
        if self.deny_enabled and (sym in self.denylist or sym in self._deny_temp):
            self.log.info("[EVENT-BO] denylist skip %s", sym)
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_skips_total.labels(reason="denylist", symbol=sym).inc()
                except Exception as exc:
                    pass
            return
        if self._cooldown_active(sym):
            self.log.info("[EVENT-BO] cooldown active %s", sym)
            return
        ok = await self._passes_guardrails(sym)
        if not ok:
            return
        plan = await self._build_plan(sym, evt)
        if plan is None:
            return

        if self.cfg.dry_run:
            self._log_plan(plan, dry=True)
            # Publish plan event for rollups
            try:
                from engine.core.event_bus import BUS

                await BUS.publish(
                    "event_bo.plan_dry",
                    {"symbol": plan.symbol, "venue": plan.venue, "market": plan.market},
                )
            except Exception as exc:
                pass
            self._arm_cooldown(sym)
            return

        # Live execution (kept minimal; uses router wrappers; reduce-only setup optional)
        qty = await self._qty_from_notional(plan.symbol, plan.notional_usd)
        try:
            await self.router.place_entry(
                plan.symbol,
                "BUY",
                qty,
                venue=plan.venue,
                intent="EVENT",
                market=plan.market,
            )
            await self.router.amend_stop_reduce_only(plan.symbol, "SELL", plan.sl_price, qty)
            tp1_qty = max(0.0, qty * float(self.cfg.tp1_portion))
            tp2_qty = max(0.0, qty * float(self.cfg.tp2_portion))
            # Optional reduce-only limits if supported
            try:
                await self.router.place_reduce_only_limit(
                    plan.symbol, "SELL", tp1_qty, plan.tp1_price
                )  # type: ignore[attr-defined]
                await self.router.place_reduce_only_limit(
                    plan.symbol, "SELL", tp2_qty, plan.tp2_price
                )  # type: ignore[attr-defined]
            except Exception as exc:
                pass
            # Emit metrics and publish open event for trailer
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_trades_total.labels(
                        venue=plan.venue, symbol=plan.symbol
                    ).inc()
                except Exception as exc:
                    pass
            try:
                from engine.core.event_bus import BUS

                await BUS.publish(
                    "strategy.event_breakout_open",
                    {"symbol": plan.symbol, "market": plan.market},
                )
                await BUS.publish(
                    "event_bo.trade",
                    {"symbol": plan.symbol, "venue": plan.venue, "market": plan.market},
                )
                await BUS.publish(
                    "event_bo.plan_live",
                    {"symbol": plan.symbol, "venue": plan.venue, "market": plan.market},
                )
            except Exception as exc:
                pass
        except Exception as exc:
            self.log.warning("[EVENT-BO] execution failed for %s: %s", sym, exc)
        self._log_plan(plan, dry=False)
        self._arm_cooldown(sym)

    async def _build_plan(self, sym: str, evt: dict[str, Any]) -> BreakoutPlan | None:
        venue = "BINANCE"  # our router determines ven/back-end; label retained for downstream
        px = await self._last(sym)
        if not px:
            self.log.warning("[EVENT-BO] no price for %s", sym)
            return None
        minutes = self._minutes_since(evt)
        size = float(self.cfg.size_usd)
        half = bool(minutes is not None and minutes < self.cfg.half_size_minutes)
        notional = size * 0.5 if half else size
        lev = int(
            self.cfg.leverage_major if sym.startswith(("BTC", "ETH")) else self.cfg.leverage_default
        )
        sl = await self._sl_min3low_or_atr(sym, px)
        if sl is None or sl >= px:
            atr = await self._atr(sym) or 0.0
            sl = max(1e-8, px - 1.5 * atr)
        tp1 = px * (1.0 + float(self.cfg.tp1_pct))
        tp2 = px * (1.0 + float(self.cfg.tp2_pct))
        atrv = await self._atr(sym) or 0.0
        trail_usd = atrv * float(self.cfg.trail_atr_mult)
        # rounding helpers best-effort
        try:
            sl = self.router.round_tick(sym, sl)  # type: ignore[attr-defined]
            tp1 = self.router.round_tick(sym, tp1)  # type: ignore[attr-defined]
            tp2 = self.router.round_tick(sym, tp2)  # type: ignore[attr-defined]
        except Exception as exc:
            pass
        qualified = f"{sym}.BINANCE"
        market_choice = resolve_market_choice(qualified, self.cfg.default_market)
        plan = BreakoutPlan(
            symbol=sym,
            venue=venue,
            side="BUY",
            notional_usd=notional,
            leverage=lev,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            trail_atr_usd=trail_usd,
            half_applied=half,
            market=market_choice,
        )
        if half:
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_half_size_applied_total.labels(symbol=sym).inc()
                except Exception as exc:
                    pass
            try:
                from engine.core.event_bus import BUS

                await BUS.publish("event_bo.half", {"symbol": sym})
            except Exception as exc:
                pass
        return plan

    async def _passes_guardrails(self, sym: str) -> bool:
        kl = await self._klines(sym, interval="1m", limit=31)
        if not kl or len(kl) < 2:
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_skips_total.labels(reason="no_klines", symbol=sym).inc()
                except Exception as exc:
                    pass
            return False
        try:
            p0 = float(kl[0][1])
            plast = float(kl[-1][4])
            if p0 <= 0:
                return False
            ch30 = (plast - p0) / p0
            if ch30 >= float(self.cfg.late_chase_pct_30m):
                self.log.info("[EVENT-BO] late-chase %s ch30=%.2f%%", sym, ch30 * 100.0)
                if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                    try:
                        self._MET.event_bo_skips_total.labels(reason="late_chase", symbol=sym).inc()
                    except Exception as exc:
                        pass
                try:
                    from engine.core.event_bus import BUS

                    await BUS.publish("event_bo.skip", {"symbol": sym, "reason": "late_chase"})
                except Exception as exc:
                    pass
                return False
            notional_1m = float(kl[-1][7] or 0.0)
        except Exception as exc:
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_skips_total.labels(reason="parse_error", symbol=sym).inc()
                except Exception as exc:
                    pass
            try:
                from engine.core.event_bus import BUS

                await BUS.publish("event_bo.skip", {"symbol": sym, "reason": "parse_error"})
            except Exception as exc:
                pass
            return False
        bt = await self._book_ticker(sym)
        bid = float(bt.get("bidPrice") or 0.0)
        ask = float(bt.get("askPrice") or 0.0)
        mid = (bid + ask) / 2.0 if (bid and ask) else 0.0
        spread_pct = abs(ask - bid) / mid if mid else 0.0
        if spread_pct >= float(self.cfg.max_spread_pct):
            self.log.info("[EVENT-BO] wide spread %s spread=%.4f%%", sym, spread_pct * 100.0)
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_skips_total.labels(reason="spread", symbol=sym).inc()
                except Exception as exc:
                    pass
            try:
                from engine.core.event_bus import BUS

                await BUS.publish("event_bo.skip", {"symbol": sym, "reason": "spread"})
            except Exception as exc:
                pass
            return False
        if notional_1m < float(self.cfg.min_notional_1m_usd):
            self.log.info("[EVENT-BO] low notional %s n1m=%.0f", sym, notional_1m)
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_skips_total.labels(reason="notional", symbol=sym).inc()
                except Exception as exc:
                    pass
            try:
                from engine.core.event_bus import BUS

                await BUS.publish("event_bo.skip", {"symbol": sym, "reason": "notional"})
            except Exception as exc:
                pass
            return False
        return True

    def _cooldown_active(self, sym: str) -> bool:
        now = float(self.clock.time())
        until = float(self._cooldowns.get(sym) or 0.0)
        return now < until

    def _arm_cooldown(self, sym: str) -> None:
        self._cooldowns[sym] = float(self.clock.time() + 60.0 * self.cfg.cooldown_minutes)

    def _minutes_since(self, evt: dict[str, Any]) -> float | None:
        try:
            t = evt.get("time")
            if t is None:
                return None
            # Accept ms or seconds
            val = float(t)
            if val > 1e12:
                # assume ms
                base_sec = val / 1000.0
            else:
                base_sec = val
            return max(0.0, float(self.clock.time()) - base_sec) / 60.0
        except Exception as exc:
            return None

    def _log_plan(self, plan: BreakoutPlan, dry: bool) -> None:
        tag = "DRY" if dry else "LIVE"
        try:
            self.log.info(
                "[EVENT-BO:%s] %s %s/%s notional=$%d lev=%s SL=%.8f TP1=%.8f TP2=%.8f trail≈$%.6f",
                tag,
                plan.symbol,
                plan.venue,
                plan.market,
                int(round(plan.notional_usd)),
                plan.leverage,
                float(plan.sl_price),
                float(plan.tp1_price),
                float(plan.tp2_price),
                float(plan.trail_atr_usd),
            )
            if self.cfg.metrics_enabled and getattr(self, "_MET", None) is not None:
                try:
                    self._MET.event_bo_plans_total.labels(
                        venue=plan.venue,
                        symbol=plan.symbol,
                        dry="true" if dry else "false",
                    ).inc()
                except Exception as exc:
                    pass
            # Emit rollup events (fire-and-forget)
            try:
                from engine.core.event_bus import BUS

                BUS.fire(
                    "event_bo.plan_dry" if dry else "event_bo.plan_live",
                    {"symbol": plan.symbol, "venue": plan.venue, "market": plan.market},
                )
            except Exception as exc:
                pass
        except Exception as exc:
            pass

    async def _qty_from_notional(self, sym: str, usd: float) -> float:
        px = await self._last(sym)
        if not px:
            return 0.0
        qty = float(usd) / float(px)
        try:
            return self.router.round_step(sym, qty)  # type: ignore[attr-defined]
        except Exception as exc:
            return qty

    async def _atr(self, sym: str) -> float:
        # Best-effort ATR from klines
        try:
            kl = await self._klines(
                sym, interval=self.cfg.atr_tf, limit=max(self.cfg.atr_n + 1, 15)
            )
            if not kl or len(kl) < 2:
                return 0.0
            prev_close = None
            trs = []
            for row in kl[-(self.cfg.atr_n + 1) :]:
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
            trs = trs[1:]  # drop first seed
            return sum(trs) / len(trs)
        except Exception as exc:
            return 0.0

    async def _sl_min3low_or_atr(self, sym: str, entry_px: float) -> float | None:
        try:
            kl = await self._klines(sym, interval="1m", limit=4)
            if not kl or len(kl) < 4:
                return None
            l2 = float(kl[-2][3])
            l3 = float(kl[-3][3])
            l4 = float(kl[-4][3])
            low3 = min(l2, l3, l4)
        except Exception as exc:
            low3 = None
        atr = await self._atr(sym) or 0.0
        if low3 is None:
            return entry_px - atr
        return min(low3, entry_px - atr)

    async def _last(self, sym: str) -> float | None:
        if self.md and hasattr(self.md, "last"):
            try:
                px = self.md.last(sym)
                if hasattr(px, "__await__"):
                    px = await px
                return float(px) if px else None
            except Exception as exc:
                pass
        try:
            px = await self.router.get_last_price(f"{sym}.BINANCE")
            return float(px) if px else None
        except Exception as exc:
            return None

    async def _klines(self, sym: str, interval: str, limit: int) -> list:
        if self.md and hasattr(self.md, "klines"):
            res = self.md.klines(sym, interval, limit)
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, list):
                return res
        try:
            client = self.router.exchange_client()
            if client and hasattr(client, "klines"):
                out = client.klines(sym, interval=interval, limit=limit)
                if hasattr(out, "__await__"):
                    out = await out
                return out if isinstance(out, list) else []
        except Exception as exc:
            pass
        return []

    async def _book_ticker(self, sym: str) -> dict[str, Any]:
        if self.md and hasattr(self.md, "book_ticker"):
            out = self.md.book_ticker(sym)
            if hasattr(out, "__await__"):
                out = await out
            return out if isinstance(out, dict) else {}
        try:
            client = self.router.exchange_client()
            if client and hasattr(client, "book_ticker"):
                out = client.book_ticker(sym)
                if hasattr(out, "__await__"):
                    out = await out
                return out if isinstance(out, dict) else {}
        except Exception as exc:
            pass
        return {}

    def _load_denylist(self, path: str) -> set[str]:
        syms: set[str] = set()
        try:
            with open(path, encoding="utf-8") as fh:
                for raw in fh:
                    line = (raw or "").strip().upper()
                    if not line or line.startswith("#"):
                        continue
                    syms.add(line)
        except FileNotFoundError:
            return syms
        except Exception as exc:
            return syms
        return syms

    # Handle skip events to build entropy and temporarily denylist noisy symbols
    def on_skip_entropy(self, evt: dict[str, Any]) -> None:
        if not self._entropy_enabled:
            return
        sym = (evt.get("symbol") or "").upper()
        reason = str(evt.get("reason") or "").lower()
        if not sym or not reason:
            return
        now = float(self.clock.time())
        reasons = self._entropy_reasons.setdefault(sym, {})
        reasons[reason] = now
        # prune
        cutoff = now - self._entropy_window
        for r, ts in list(reasons.items()):
            if ts < cutoff:
                reasons.pop(r, None)
        if len(reasons) >= self._entropy_reason_count:
            self._deny_temp[sym] = now + self._entropy_dur
            self.log.info("[EVENT-BO] entropy deny %s for %.0f min", sym, self._entropy_dur / 60.0)
