from __future__ import annotations

"""Real-time momentum breakout module wired to the streaming tick feed."""

import logging
import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, Optional

from engine import metrics
from engine.core.market_resolver import resolve_market_choice

logger = logging.getLogger("engine.momentum.realtime")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return ()
    out: list[str] = []
    for token in raw.split(","):
        symbol = token.strip().upper()
        if not symbol:
            continue
        symbol = symbol.replace(".BINANCE", "")
        out.append(symbol)
    return tuple(sorted(set(out)))


@dataclass(frozen=True)
class MomentumRealtimeConfig:
    enabled: bool
    dry_run: bool
    symbols: tuple[str, ...]
    window_sec: float
    baseline_sec: float
    min_ticks: int
    pct_move_threshold: float
    volume_spike_ratio: float
    cooldown_sec: float
    quote_usd: float
    stop_loss_pct: float
    trail_pct: float
    take_profit_pct: float
    allow_shorts: bool
    prefer_futures: bool


def load_momentum_rt_config() -> MomentumRealtimeConfig:
    symbols = _env_list("MOMENTUM_RT_SYMBOLS")
    window_sec = max(10.0, _env_float("MOMENTUM_RT_WINDOW_SEC", 45.0))
    baseline_sec = max(window_sec, _env_float("MOMENTUM_RT_BASELINE_SEC", 6 * 60.0))
    pct_move = _env_float("MOMENTUM_RT_MOVE_THRESHOLD_PCT", 1.8) / 100.0
    volume_ratio = max(1.0, _env_float("MOMENTUM_RT_VOLUME_SPIKE_RATIO", 2.0))
    stop_loss_pct = max(0.001, _env_float("MOMENTUM_RT_STOP_PCT", 0.8) / 100.0)
    trail_pct = max(0.001, _env_float("MOMENTUM_RT_TRAIL_PCT", 1.2) / 100.0)
    take_profit_pct = max(0.0, _env_float("MOMENTUM_RT_TP_PCT", 3.5) / 100.0)
    prefer_futures = _env_bool("MOMENTUM_RT_PREFER_FUTURES", True)
    return MomentumRealtimeConfig(
        enabled=_env_bool("MOMENTUM_RT_ENABLED", False),
        dry_run=_env_bool("MOMENTUM_RT_DRY_RUN", True),
        symbols=symbols,
        window_sec=window_sec,
        baseline_sec=baseline_sec,
        min_ticks=max(2, _env_int("MOMENTUM_RT_MIN_TICKS", 3)),
        pct_move_threshold=pct_move,
        volume_spike_ratio=volume_ratio,
        cooldown_sec=max(15.0, _env_float("MOMENTUM_RT_COOLDOWN_SEC", 180.0)),
        quote_usd=max(25.0, _env_float("MOMENTUM_RT_QUOTE_USD", 150.0)),
        stop_loss_pct=stop_loss_pct,
        trail_pct=trail_pct,
        take_profit_pct=take_profit_pct,
        allow_shorts=_env_bool("MOMENTUM_RT_ALLOW_SHORTS", False),
        prefer_futures=prefer_futures,
    )


def _recent(points: Deque[tuple[float, float, float]], cutoff: float) -> Iterable[tuple[float, float, float]]:
    for ts, price, volume in points:
        if ts >= cutoff:
            yield ts, price, volume


class MomentumStrategyModule:
    """Detect sudden breakouts from real-time ticks and emit strategy orders."""

    def __init__(
        self,
        cfg: Optional[MomentumRealtimeConfig] = None,
        *,
        clock=time,
    ) -> None:
        self.cfg = cfg or load_momentum_rt_config()
        self.enabled = self.cfg.enabled
        self._clock = clock
        self._windows: Dict[str, Deque[tuple[float, float, float]]] = defaultdict(deque)
        self._cooldown_until: Dict[str, float] = defaultdict(float)

    def handle_tick(
        self,
        symbol: str,
        price: float,
        ts: float,
        volume: Optional[float] = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None
        if price <= 0.0 or not math.isfinite(price):
            return None
        if not symbol:
            return None

        base = symbol.split(".")[0].upper()
        venue = symbol.split(".")[1].upper() if "." in symbol else "BINANCE"
        if self.cfg.symbols and base not in self.cfg.symbols:
            return None

        now = ts if ts is not None else self._clock.time()
        window = self._windows[base]
        vol = float(volume or 0.0)
        window.append((now, float(price), vol))

        cutoff = now - self.cfg.baseline_sec
        while window and window[0][0] < cutoff:
            window.popleft()

        fast_cutoff = now - self.cfg.window_sec
        fast_points = list(_recent(window, fast_cutoff))
        if len(fast_points) < self.cfg.min_ticks:
            return None

        prices = [p for _, p, _ in fast_points]
        lows = min(prices)
        highs = max(prices)
        if lows <= 0.0 or not math.isfinite(lows):
            return None
        if not math.isfinite(highs):
            return None

        pct_move_up = (price - lows) / lows if price > lows else 0.0
        pct_move_down = (highs - price) / highs if price < highs else 0.0

        baseline_prices = [p for ts_val, p, _ in window if ts_val < fast_cutoff]
        baseline_high = max(baseline_prices) if baseline_prices else highs
        baseline_low = min(baseline_prices) if baseline_prices else lows

        recent_volume = sum(v for _, _, v in fast_points)
        baseline_volumes = [v for ts_val, _, v in window if ts_val < fast_cutoff and v > 0.0]
        if baseline_volumes:
            baseline_avg_volume = sum(baseline_volumes) / max(len(baseline_volumes), 1)
        else:
            total = sum(v for _, _, v in window)
            baseline_avg_volume = total / max(len(window), 1)
        if baseline_avg_volume <= 0.0:
            volume_ratio = float("inf") if recent_volume > 0 else 0.0
        else:
            volume_ratio = recent_volume / baseline_avg_volume

        try:
            metrics.momentum_rt_volume_ratio.labels(symbol=base, venue=venue.lower()).set(
                volume_ratio if math.isfinite(volume_ratio) else 0.0
            )
            metrics.momentum_rt_window_return_pct.labels(symbol=base, venue=venue.lower()).set(
                pct_move_up * 100.0 if pct_move_up >= pct_move_down else -pct_move_down * 100.0
            )
        except Exception:
            pass

        if now < self._cooldown_until.get(base, 0.0):
            return None

        side: Optional[str] = None
        reason = ""
        if (
            pct_move_up >= self.cfg.pct_move_threshold
            and price >= baseline_high * 1.0005
            and volume_ratio >= self.cfg.volume_spike_ratio
        ):
            side = "BUY"
            reason = "breakout_up"
        elif (
            self.cfg.allow_shorts
            and pct_move_down >= self.cfg.pct_move_threshold
            and price <= baseline_low * (1.0 - 0.0005)
            and volume_ratio >= self.cfg.volume_spike_ratio
        ):
            side = "SELL"
            reason = "breakout_down"

        if side is None:
            return None

        cooldown_until = now + self.cfg.cooldown_sec
        self._cooldown_until[base] = cooldown_until

        default_market = "futures" if (self.cfg.prefer_futures or side == "SELL") else "spot"
        market_choice = resolve_market_choice(symbol, default_market)

        if side == "BUY":
            stop_price = price * (1.0 - self.cfg.stop_loss_pct)
            take_profit = price * (1.0 + self.cfg.take_profit_pct) if self.cfg.take_profit_pct > 0 else None
        else:
            stop_price = price * (1.0 + self.cfg.stop_loss_pct)
            take_profit = price * (1.0 - self.cfg.take_profit_pct) if self.cfg.take_profit_pct > 0 else None
        trail_distance = price * self.cfg.trail_pct

        try:
            metrics.momentum_rt_breakouts_total.labels(
                symbol=base, venue=venue.lower(), side=side, reason=reason
            ).inc()
            metrics.momentum_rt_cooldown_epoch.labels(symbol=base, venue=venue.lower()).set(cooldown_until)
        except Exception:
            pass

        logger.info(
            "[MOMO-RT] breakout %s %s move=%.2f%% vol_ratio=%.2f", base, side, pct_move_up * 100.0, volume_ratio
        )

        meta = {
            "pct_move": pct_move_up * 100.0 if side == "BUY" else pct_move_down * 100.0,
            "volume_ratio": volume_ratio,
            "window_sec": self.cfg.window_sec,
            "stop_price": stop_price,
            "trail_distance": trail_distance,
        }
        if take_profit is not None:
            meta["take_profit"] = take_profit
        meta["baseline_high"] = baseline_high
        meta["baseline_low"] = baseline_low

        tag = f"momentum_rt_{reason}"
        return {
            "symbol": symbol,
            "side": side,
            "quote": float(self.cfg.quote_usd),
            "tag": tag,
            "meta": meta,
            "market": market_choice,
        }

