from __future__ import annotations

import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from engine import metrics


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


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return []
    out: list[str] = []
    for token in raw.split(","):
        norm = token.strip().upper()
        if not norm:
            continue
        out.append(norm.replace(".BINANCE", ""))
    return sorted(set(out))


@dataclass(frozen=True)
class ScalpConfig:
    enabled: bool
    dry_run: bool
    symbols: tuple[str, ...]
    window_sec: float
    min_samples: int
    min_range_bps: float
    lower_threshold: float
    upper_threshold: float
    rsi_length: int
    rsi_buy: float
    rsi_sell: float
    stop_bps: float
    take_profit_bps: float
    quote_usd: float
    cooldown_sec: float
    allow_shorts: bool


def load_scalp_config() -> ScalpConfig:
    symbols = tuple(_env_list("SCALP_SYMBOLS")) or ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    return ScalpConfig(
        enabled=_env_bool("SCALP_ENABLED", False),
        dry_run=_env_bool("SCALP_DRY_RUN", True),
        symbols=symbols,
        window_sec=max(30.0, _env_float("SCALP_WINDOW_SEC", 240.0)),
        min_samples=max(5, _env_int("SCALP_MIN_SAMPLES", 30)),
        min_range_bps=max(5.0, _env_float("SCALP_MIN_RANGE_BPS", 12.0)),
        lower_threshold=min(0.45, max(0.0, _env_float("SCALP_LOWER_THRESHOLD", 0.2))),
        upper_threshold=max(0.55, min(1.0, _env_float("SCALP_UPPER_THRESHOLD", 0.8))),
        rsi_length=max(2, _env_int("SCALP_RSI_LENGTH", 2)),
        rsi_buy=max(0.0, _env_float("SCALP_RSI_BUY", 15.0)),
        rsi_sell=min(100.0, _env_float("SCALP_RSI_SELL", 85.0)),
        stop_bps=max(5.0, _env_float("SCALP_STOP_BPS", 25.0)),
        take_profit_bps=max(5.0, _env_float("SCALP_TP_BPS", 35.0)),
        quote_usd=max(10.0, _env_float("SCALP_QUOTE_USD", 125.0)),
        cooldown_sec=max(10.0, _env_float("SCALP_COOLDOWN_SEC", 45.0)),
        allow_shorts=_env_bool("SCALP_ALLOW_SHORTS", True),
    )


def _rsi(prices: list[float], length: int) -> Optional[float]:
    if length <= 1 or len(prices) <= length:
        return None
    gains = 0.0
    losses = 0.0
    for idx in range(-length, 0):
        delta = prices[idx] - prices[idx - 1]
        if delta >= 0:
            gains += delta
        else:
            losses += -delta
    avg_gain = gains / length
    avg_loss = losses / length
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class ScalpStrategyModule:
    """Short-horizon mean-reversion scalper described in the strategy framework."""

    def __init__(self, cfg: Optional[ScalpConfig] = None, clock=time):
        self.cfg = cfg or load_scalp_config()
        self.enabled = self.cfg.enabled
        self._clock = clock
        self._windows: Dict[str, Deque[tuple[float, float]]] = defaultdict(deque)
        self._cooldown_until: Dict[str, float] = defaultdict(float)
        self._last_side: Dict[str, str] = {}

    def handle_tick(self, symbol: str, price: float, ts: float) -> Optional[dict]:
        if not self.enabled or price <= 0.0 or not math.isfinite(price):
            return None
        base = symbol.split(".")[0].upper()
        if base not in self.cfg.symbols:
            return None
        window = self._windows[base]
        window.append((ts, price))
        cutoff = ts - float(self.cfg.window_sec)
        while window and window[0][0] < cutoff:
            window.popleft()
        if len(window) < self.cfg.min_samples:
            return None
        prices = [p for _, p in window]
        rsi_value = _rsi(prices, self.cfg.rsi_length)
        if rsi_value is None:
            return None

        low = min(prices)
        high = max(prices)
        span = max(high - low, 1e-9)
        price_pos = (price - low) / span if span > 0 else 0.5
        range_bps = (span / price) * 10_000.0 if price > 0 else 0.0

        venue = symbol.split(".")[1].lower() if "." in symbol else "binance"
        try:
            metrics.scalp_range_width_bp.labels(symbol=base, venue=venue).set(range_bps)
            metrics.scalp_position.labels(symbol=base, venue=venue).set(price_pos)
            metrics.scalp_rsi.labels(symbol=base, venue=venue).set(rsi_value)
        except Exception:
            pass

        if range_bps < self.cfg.min_range_bps:
            return None

        now = ts or self._clock.time()
        if now < self._cooldown_until.get(base, 0.0):
            return None

        side: Optional[str] = None
        reason = ""
        if price_pos <= self.cfg.lower_threshold and rsi_value <= self.cfg.rsi_buy:
            side = "BUY"
            reason = "lower_band"
        elif self.cfg.allow_shorts and price_pos >= self.cfg.upper_threshold and rsi_value >= self.cfg.rsi_sell:
            side = "SELL"
            reason = "upper_band"
        if side is None:
            return None

        # Block immediate repeats in same direction until price reverts
        prev_side = self._last_side.get(base)
        if prev_side == side:
            return None

        self._last_side[base] = side
        self._cooldown_until[base] = now + self.cfg.cooldown_sec

        stop_factor = self.cfg.stop_bps / 10_000.0
        tp_factor = self.cfg.take_profit_bps / 10_000.0
        if side == "BUY":
            stop_price = price * (1.0 - stop_factor)
            target_price = price * (1.0 + tp_factor)
        else:
            stop_price = price * (1.0 + stop_factor)
            target_price = price * (1.0 - tp_factor)

        try:
            metrics.scalp_signals_total.labels(symbol=base, venue=venue, side=side, reason=reason).inc()
        except Exception:
            pass

        return {
            "symbol": symbol,
            "side": side,
            "quote": float(self.cfg.quote_usd),
            "tag": f"scalp_{reason}",
            "meta": {
                "range_bps": range_bps,
                "position": price_pos,
                "rsi": rsi_value,
                "stop_price": stop_price,
                "take_profit": target_price,
            },
            "market": "futures" if self.cfg.allow_shorts else "spot",
        }
