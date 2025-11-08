from __future__ import annotations

import asyncio
import logging
import math
import os
import statistics
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from engine.core.market_resolver import resolve_market_choice
from engine.metrics import (
    momentum_breakout_candidates_total,
    momentum_breakout_cooldown_epoch,
    momentum_breakout_orders_total,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list(name: str) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return []
    out: List[str] = []
    for token in raw.split(","):
        token = token.strip().upper()
        if not token:
            continue
        out.append(token.replace(".BINANCE", ""))
    return out


@dataclass(frozen=True)
class MomentumConfig:
    enabled: bool
    dry_run: bool
    use_scanner: bool
    symbols: Sequence[str]
    scanner_top_n: int
    interval_sec: float
    lookback_bars: int
    pct_move_threshold: float
    volume_window: int
    volume_baseline_window: int
    volume_multiplier: float
    atr_length: int
    atr_interval: str
    stop_atr_mult: float
    trail_atr_mult: float
    take_profit_pct: float
    cooldown_sec: float
    notional_usd: float
    max_extension_pct: float
    prefer_futures: bool
    leverage_major: int
    leverage_default: int
    max_signals_per_cycle: int
    min_quote_volume_usd: float
    default_market: str


def load_momentum_config() -> MomentumConfig:
    symbols = _env_list("MOMENTUM_SYMBOLS")
    lookback_min = max(3, _env_int("MOMENTUM_LOOKBACK_MINUTES", 15))
    prefer_futures = _env_bool("MOMENTUM_PREFER_FUTURES", True)
    default_market_raw = os.getenv("MOMENTUM_DEFAULT_MARKET", "").strip().lower()
    default_market = default_market_raw or ("futures" if prefer_futures else "spot")
    if default_market not in {"spot", "margin", "futures", "options"}:
        default_market = "futures" if prefer_futures else "spot"
    return MomentumConfig(
        enabled=_env_bool("MOMENTUM_ENABLED", False),
        dry_run=_env_bool("MOMENTUM_DRY_RUN", True),
        use_scanner=_env_bool("MOMENTUM_USE_SCANNER", True),
        symbols=symbols,
        scanner_top_n=max(1, _env_int("MOMENTUM_SCANNER_TOP_N", 8)),
        interval_sec=max(5.0, _env_float("MOMENTUM_INTERVAL_SEC", 30.0)),
        lookback_bars=lookback_min,
        pct_move_threshold=_env_float("MOMENTUM_MOVE_THRESHOLD_PCT", 2.5) / 100.0,
        volume_window=max(1, _env_int("MOMENTUM_VOLUME_WINDOW", 3)),
        volume_baseline_window=max(3, _env_int("MOMENTUM_VOLUME_BASELINE_WINDOW", 12)),
        volume_multiplier=max(1.0, _env_float("MOMENTUM_VOLUME_MULTIPLIER", 2.5)),
        atr_length=max(5, _env_int("MOMENTUM_ATR_LENGTH", 14)),
        atr_interval=os.getenv("MOMENTUM_ATR_INTERVAL", "1m"),
        stop_atr_mult=max(0.5, _env_float("MOMENTUM_STOP_ATR_MULT", 1.6)),
        trail_atr_mult=max(0.5, _env_float("MOMENTUM_TRAIL_ATR_MULT", 1.2)),
        take_profit_pct=_env_float("MOMENTUM_TP_PCT", 4.0) / 100.0,
        cooldown_sec=max(30.0, _env_float("MOMENTUM_COOLDOWN_SEC", 600.0)),
        notional_usd=max(25.0, _env_float("MOMENTUM_NOTIONAL_USD", 150.0)),
        max_extension_pct=_env_float("MOMENTUM_MAX_EXTENSION_PCT", 12.0) / 100.0,
        prefer_futures=prefer_futures,
        leverage_major=max(1, _env_int("MOMENTUM_LEVERAGE_MAJOR", 2)),
        leverage_default=max(1, _env_int("MOMENTUM_LEVERAGE_DEFAULT", 2)),
        max_signals_per_cycle=max(1, _env_int("MOMENTUM_MAX_SIGNALS_PER_CYCLE", 3)),
        min_quote_volume_usd=max(50_000.0, _env_float("MOMENTUM_MIN_QUOTE_VOL_USD", 250_000.0)),
        default_market=default_market,
    )


@dataclass
class MomentumPlan:
    symbol: str
    venue: str
    notional_usd: float
    stop_price: float
    trail_distance: float
    take_profit: float
    leverage: int
    price: float
    half_size: bool = False
    market: str = "spot"


class MomentumBreakout:
    """Momentum breakout scanner + executor for Binance spot/futures markets."""

    def __init__(
        self,
        router,
        risk,
        cfg: Optional[MomentumConfig] = None,
        scanner=None,
        clock=time,
    ) -> None:
        self.cfg = cfg or load_momentum_config()
        self.router = router
        self.risk = risk
        self.scanner = scanner
        self.clock = clock
        self.log = logging.getLogger("engine.momentum_breakout")
        self._cooldowns: Dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        if not self.cfg.enabled or self._task:
            return
        loop = asyncio.get_running_loop()
        self._running = True
        self._task = loop.create_task(self._run(), name="momentum-breakout")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        interval = float(self.cfg.interval_sec)
        while self._running:
            started = self.clock.time()
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                self.log.warning("[MOMO] scan loop error: %s", exc, exc_info=True)
            elapsed = self.clock.time() - started
            await asyncio.sleep(max(1.0, interval - min(interval, elapsed)))

    async def _scan_once(self) -> None:
        symbols = await self._resolve_symbols()
        if not symbols:
            return
        triggers = 0
        for sym in symbols:
            if triggers >= self.cfg.max_signals_per_cycle:
                break
            try:
                plan = await self._evaluate_symbol(sym)
            except Exception as exc:
                self.log.debug("[MOMO] evaluate %s failed: %s", sym, exc)
                continue
            if plan is None:
                continue
            triggers += 1
            await self._execute(plan)

    async def _resolve_symbols(self) -> List[str]:
        if self.cfg.use_scanner and self.scanner:
            try:
                selected = self.scanner.get_selected()[: self.cfg.scanner_top_n]
                if selected:
                    return [sym.split(".")[0].upper() for sym in selected]
            except Exception:
                pass
        if self.cfg.symbols:
            return [s.split(".")[0].upper() for s in self.cfg.symbols]
        try:
            universe = self.router.trade_symbols()
            return [s.split(".")[0].upper() for s in universe][: self.cfg.scanner_top_n]
        except Exception:
            return []

    async def _evaluate_symbol(self, symbol: str) -> Optional[MomentumPlan]:
        now = float(self.clock.time())
        if not self._cooldown_ready(symbol, now):
            return None
        client = self.router.exchange_client()
        if client is None or not hasattr(client, "klines"):
            return None
        limit = max(
            self.cfg.lookback_bars + self.cfg.volume_baseline_window + self.cfg.volume_window + 5,
            self.cfg.atr_length + 5,
        )
        raw = client.klines(symbol, interval=self.cfg.atr_interval, limit=limit)
        if hasattr(raw, "__await__"):
            raw = await raw
        if not isinstance(raw, list) or len(raw) < (
            self.cfg.lookback_bars + self.cfg.volume_window + 3
        ):
            return None

        closes = [float(row[4]) for row in raw]
        highs = [float(row[2]) for row in raw]
        lows = [float(row[3]) for row in raw]
        qvols = [float(row[7]) for row in raw]
        vols = [float(row[5]) for row in raw]
        price = closes[-1]
        if not math.isfinite(price) or price <= 0:
            return None
        lookback_idx = (
            -self.cfg.lookback_bars if self.cfg.lookback_bars < len(closes) else -len(closes)
        )
        baseline_price = closes[lookback_idx]
        if baseline_price <= 0:
            return None
        move = (price - baseline_price) / baseline_price
        recent_high = max(highs[lookback_idx:])
        prior_high = max(highs[:lookback_idx]) if abs(lookback_idx) < len(highs) else recent_high
        breakout = price >= prior_high and move >= self.cfg.pct_move_threshold

        recent_vol = sum(vols[-self.cfg.volume_window :])
        baseline_slice = vols[
            -(self.cfg.volume_window + self.cfg.volume_baseline_window) : -self.cfg.volume_window
        ]
        baseline_vol = statistics.mean(baseline_slice) if baseline_slice else 0.0
        volume_boost = (
            baseline_vol > 0 and (recent_vol / baseline_vol) >= self.cfg.volume_multiplier
        )
        notional_recent = sum(qvols[-self.cfg.volume_window :])
        if notional_recent < self.cfg.min_quote_volume_usd:
            momentum_breakout_candidates_total.labels(symbol, "BINANCE", "low_volume").inc()
            return None

        if not breakout or not volume_boost:
            reason = "no_breakout" if not breakout else "no_volume"
            momentum_breakout_candidates_total.labels(symbol, "BINANCE", reason).inc()
            return None

        window_lows = lows[lookback_idx:]
        low_anchor = min(window_lows) if window_lows else price
        extension = (price - low_anchor) / max(low_anchor, 1e-9)
        if extension >= self.cfg.max_extension_pct:
            momentum_breakout_candidates_total.labels(symbol, "BINANCE", "extended").inc()
            return None

        atr = self._atr(highs, lows, closes, self.cfg.atr_length)
        if atr <= 0:
            momentum_breakout_candidates_total.labels(symbol, "BINANCE", "no_atr").inc()
            return None

        stop_price = max(price - atr * self.cfg.stop_atr_mult, low_anchor)
        trail_distance = atr * self.cfg.trail_atr_mult
        take_profit = price * (1.0 + self.cfg.take_profit_pct)
        lev = (
            self.cfg.leverage_major
            if symbol.startswith(("BTC", "ETH"))
            else self.cfg.leverage_default
        )
        qualified = f"{symbol}.BINANCE"
        market_choice = resolve_market_choice(qualified, self.cfg.default_market)
        plan = MomentumPlan(
            symbol=qualified,
            venue="BINANCE",
            notional_usd=self.cfg.notional_usd,
            stop_price=float(stop_price),
            trail_distance=float(trail_distance),
            take_profit=float(take_profit),
            leverage=lev,
            price=float(price),
            half_size=False,
            market=market_choice,
        )
        momentum_breakout_candidates_total.labels(symbol, "BINANCE", "trigger").inc()
        return plan

    async def _execute(self, plan: MomentumPlan) -> None:
        symbol = plan.symbol
        clean = symbol.split(".")[0]
        now = float(self.clock.time())
        ok, err = self.risk.check_order(
            symbol=symbol,
            side="BUY",
            quote=plan.notional_usd,
            quantity=None,
            market=plan.market,
        )
        if not ok:
            reason = (err or {}).get("error", "risk")
            momentum_breakout_orders_total.labels(clean, plan.venue, reason).inc()
            self._arm_cooldown(clean, now)
            return
        if self.cfg.dry_run:
            self.log.info(
                "[MOMO:DRY] %s breakout @%.4f notional=$%.0f stop=%.4f tp=%.4f market=%s",
                symbol,
                plan.price,
                plan.notional_usd,
                plan.stop_price,
                plan.take_profit,
                plan.market,
            )
            momentum_breakout_orders_total.labels(clean, plan.venue, "simulated").inc()
            self._arm_cooldown(clean, now)
            return
        qty = 0.0
        try:
            result = await self.router.market_quote(
                symbol, "BUY", plan.notional_usd, market=plan.market
            )
            avg = float(result.get("avg_fill_price") or plan.price)
            qty = float(result.get("filled_qty_base") or result.get("executedQty") or 0.0)
            self.log.info(
                "[MOMO] LIVE %s qty=%.6f avg=%.4f stop=%.4f tp=%.4f trail≈%.4f market=%s",
                symbol,
                qty,
                avg,
                plan.stop_price,
                plan.take_profit,
                plan.trail_distance,
                plan.market,
            )
            momentum_breakout_orders_total.labels(clean, plan.venue, "submitted").inc()
            self._arm_cooldown(clean, now)
            if qty > 0:
                await self._arm_managed_exits(symbol, qty, plan)
        except Exception as exc:  # pragma: no cover - network/venue issues
            self.log.warning("[MOMO] execution failed for %s: %s", symbol, exc)
            momentum_breakout_orders_total.labels(clean, plan.venue, "failed").inc()

    async def _arm_managed_exits(self, symbol: str, qty: float, plan: MomentumPlan) -> None:
        try:
            await self.router.amend_stop_reduce_only(symbol, "SELL", plan.stop_price, abs(qty))
        except Exception:
            pass
        try:
            await self.router.place_reduce_only_limit(
                symbol, "SELL", abs(qty) * 0.5, plan.take_profit
            )
        except Exception:
            pass

    def _cooldown_ready(self, symbol: str, now: float) -> bool:
        until = self._cooldowns.get(symbol)
        if until and now < until:
            momentum_breakout_cooldown_epoch.labels(symbol).set(until)
            return False
        return True

    def _arm_cooldown(self, symbol: str, now: float) -> None:
        resume = now + float(self.cfg.cooldown_sec)
        self._cooldowns[symbol] = resume
        momentum_breakout_cooldown_epoch.labels(symbol).set(resume)

    @staticmethod
    def _atr(
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        length: int,
    ) -> float:
        if length <= 1 or len(highs) <= length:
            return 0.0
        trs: List[float] = []
        prev_close = closes[-length - 1]
        for i in range(len(highs) - length, len(highs)):
            high = highs[i]
            low = lows[i]
            close = closes[i]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        if not trs:
            return 0.0
        return sum(trs) / len(trs)
