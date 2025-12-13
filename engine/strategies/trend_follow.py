from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from engine.config import get_settings
from engine.config.defaults import TREND_DEFAULTS
from engine.config.env import env_bool, env_float, env_int, env_str
from engine.core.market_resolver import resolve_market_choice
from engine.universe.effective import StrategyUniverse

from . import policy_hmm
from .trend_params import TrendAutoTuner, TrendParams

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    httpx.HTTPError,
)

if TYPE_CHECKING:  # pragma: no cover
    from .symbol_scanner import SymbolScanner

_TIMEFRAME_SECONDS = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


@dataclass(frozen=True)
class TrendTF:
    interval: str
    fast: int
    slow: int
    rsi_length: int = 14


@dataclass(frozen=True)
class TrendStrategyConfig:
    enabled: bool
    dry_run: bool
    symbols: list[str]
    fetch_limit: int
    refresh_sec: int
    atr_length: int
    atr_stop_mult: float
    atr_target_mult: float
    swing_lookback: int
    rsi_long_min: float
    rsi_long_max: float
    rsi_exit: float
    risk_pct: float
    min_quote_usd: float
    fallback_equity_usd: float
    cooldown_bars: int
    allow_shorts: bool
    auto_tune_enabled: bool
    auto_tune_min_trades: int
    auto_tune_interval: int
    auto_tune_history: int
    auto_tune_win_low: float
    auto_tune_win_high: float
    auto_tune_stop_min: float
    auto_tune_stop_max: float
    auto_tune_state_path: str
    primary: TrendTF
    secondary: TrendTF
    regime: TrendTF


def load_trend_config(scanner: SymbolScanner | None = None) -> TrendStrategyConfig:
    universe = StrategyUniverse(scanner).get("trend") or []
    primary = TrendTF(
        interval=env_str("TREND_PRIMARY_INTERVAL", TREND_DEFAULTS["TREND_PRIMARY_INTERVAL"]),
        fast=env_int("TREND_PRIMARY_FAST", TREND_DEFAULTS["TREND_PRIMARY_FAST"]),
        slow=env_int("TREND_PRIMARY_SLOW", TREND_DEFAULTS["TREND_PRIMARY_SLOW"]),
        rsi_length=env_int("TREND_PRIMARY_RSI", TREND_DEFAULTS["TREND_PRIMARY_RSI"]),
    )
    secondary = TrendTF(
        interval=env_str("TREND_SECONDARY_INTERVAL", TREND_DEFAULTS["TREND_SECONDARY_INTERVAL"]),
        fast=env_int("TREND_SECONDARY_FAST", TREND_DEFAULTS["TREND_SECONDARY_FAST"]),
        slow=env_int("TREND_SECONDARY_SLOW", TREND_DEFAULTS["TREND_SECONDARY_SLOW"]),
        rsi_length=env_int("TREND_SECONDARY_RSI", TREND_DEFAULTS["TREND_SECONDARY_RSI"]),
    )
    regime = TrendTF(
        interval=env_str("TREND_REGIME_INTERVAL", TREND_DEFAULTS["TREND_REGIME_INTERVAL"]),
        fast=env_int("TREND_REGIME_FAST", TREND_DEFAULTS["TREND_REGIME_FAST"]),
        slow=env_int("TREND_REGIME_SLOW", TREND_DEFAULTS["TREND_REGIME_SLOW"]),
        rsi_length=env_int("TREND_REGIME_RSI", TREND_DEFAULTS["TREND_REGIME_RSI"]),
    )
    return TrendStrategyConfig(
        enabled=env_bool("TREND_ENABLED", TREND_DEFAULTS["TREND_ENABLED"]),
        dry_run=env_bool("TREND_DRY_RUN", TREND_DEFAULTS["TREND_DRY_RUN"]),
        symbols=list(universe),
        fetch_limit=env_int("TREND_FETCH_LIMIT", TREND_DEFAULTS["TREND_FETCH_LIMIT"]),
        refresh_sec=env_int("TREND_REFRESH_SEC", TREND_DEFAULTS["TREND_REFRESH_SEC"]),
        atr_length=env_int("TREND_ATR_LENGTH", TREND_DEFAULTS["TREND_ATR_LENGTH"]),
        atr_stop_mult=env_float("TREND_ATR_STOP_MULT", TREND_DEFAULTS["TREND_ATR_STOP_MULT"]),
        atr_target_mult=env_float("TREND_ATR_TARGET_MULT", TREND_DEFAULTS["TREND_ATR_TARGET_MULT"]),
        swing_lookback=env_int("TREND_SWING_LOOKBACK", TREND_DEFAULTS["TREND_SWING_LOOKBACK"]),
        rsi_long_min=env_float("TREND_RSI_LONG_MIN", TREND_DEFAULTS["TREND_RSI_LONG_MIN"]),
        rsi_long_max=env_float("TREND_RSI_LONG_MAX", TREND_DEFAULTS["TREND_RSI_LONG_MAX"]),
        rsi_exit=env_float("TREND_RSI_EXIT", TREND_DEFAULTS["TREND_RSI_EXIT"]),
        risk_pct=env_float("TREND_RISK_PCT", TREND_DEFAULTS["TREND_RISK_PCT"]),
        min_quote_usd=env_float("TREND_MIN_QUOTE_USD", TREND_DEFAULTS["TREND_MIN_QUOTE_USD"]),
        fallback_equity_usd=env_float(
            "TREND_FALLBACK_EQUITY", TREND_DEFAULTS["TREND_FALLBACK_EQUITY"]
        ),
        cooldown_bars=env_int("TREND_COOLDOWN_BARS", TREND_DEFAULTS["TREND_COOLDOWN_BARS"]),
        allow_shorts=env_bool("TREND_ALLOW_SHORTS", TREND_DEFAULTS["TREND_ALLOW_SHORTS"]),
        auto_tune_enabled=env_bool(
            "TREND_AUTO_TUNE_ENABLED", TREND_DEFAULTS["TREND_AUTO_TUNE_ENABLED"]
        ),
        auto_tune_min_trades=env_int(
            "TREND_AUTO_TUNE_MIN_TRADES", TREND_DEFAULTS["TREND_AUTO_TUNE_MIN_TRADES"]
        ),
        auto_tune_interval=env_int(
            "TREND_AUTO_TUNE_INTERVAL", TREND_DEFAULTS["TREND_AUTO_TUNE_INTERVAL"]
        ),
        auto_tune_history=env_int(
            "TREND_AUTO_TUNE_HISTORY", TREND_DEFAULTS["TREND_AUTO_TUNE_HISTORY"]
        ),
        auto_tune_win_low=env_float(
            "TREND_AUTO_TUNE_WIN_LOW", TREND_DEFAULTS["TREND_AUTO_TUNE_WIN_LOW"]
        ),
        auto_tune_win_high=env_float(
            "TREND_AUTO_TUNE_WIN_HIGH", TREND_DEFAULTS["TREND_AUTO_TUNE_WIN_HIGH"]
        ),
        auto_tune_stop_min=env_float(
            "TREND_AUTO_TUNE_STOP_MIN", TREND_DEFAULTS["TREND_AUTO_TUNE_STOP_MIN"]
        ),
        auto_tune_stop_max=env_float(
            "TREND_AUTO_TUNE_STOP_MAX", TREND_DEFAULTS["TREND_AUTO_TUNE_STOP_MAX"]
        ),
        auto_tune_state_path=env_str(
            "TREND_AUTO_TUNE_STATE_PATH", TREND_DEFAULTS["TREND_AUTO_TUNE_STATE_PATH"]
        ),
        primary=primary,
        secondary=secondary,
        regime=regime,
    )


def _sma(values: list[float], length: int) -> float | None:
    if length <= 0 or len(values) < length:
        return None
    return sum(values[-length:]) / float(length)


def _rsi(values: list[float], length: int) -> float | None:
    if length <= 1 or len(values) <= length:
        return None
    gains = []
    losses = []
    for i in range(-length, 0):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(klines: list[list[float]], length: int) -> float | None:
    if length <= 0 or len(klines) <= length:
        return None
    trs: list[float] = []
    prev_close = float(klines[-length - 1][4])
    for row in klines[-length:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if not trs:
        return None
    return sum(trs) / len(trs)


def _swing_low(klines: list[list[float]], lookback: int) -> float | None:
    if lookback <= 0 or len(klines) < lookback:
        return None
    lows = [float(row[3]) for row in klines[-lookback:]]
    if not lows:
        return None
    return min(lows)


class TrendStrategyModule:
    """
    Evaluates multi-timeframe SMA/RSI conditions and emits signals that align with the
    trend-following design brief captured in ``docs/PROJECT_OVERVIEW.md``.
    """

    def __init__(
        self,
        cfg: TrendStrategyConfig,
        *,
        client: _SyncKlinesClient | None = None,
        clock=time,
        logger: logging.Logger | None = None,
        scanner: SymbolScanner | None = None,
    ) -> None:
        self.cfg = cfg
        self.enabled = bool(cfg.enabled)
        self._client = client or _AsyncKlinesClient()
        self._clock = clock
        self._log = logger or logging.getLogger("engine.trend")
        self._universe = StrategyUniverse(scanner)
        self._params = TrendParams.from_config(cfg)
        self._auto_tuner = TrendAutoTuner(cfg, self._params, logger=self._log)
        self._venue = "BINANCE"
        try:
            settings = get_settings()
            self._venue = getattr(settings, "venue", "BINANCE").upper()
        except Exception as exc:
            pass
        self._default_market = "futures" if cfg.allow_shorts else "spot"
        self._cache: dict[str, dict[str, list[list[float]]]] = defaultdict(dict)
        self._last_fetch: dict[tuple[str, str], float] = defaultdict(float)
        self._state: dict[str, str] = defaultdict(lambda: "FLAT")
        self._cooldown_until: dict[str, float] = defaultdict(float)
        self._entry_quote: dict[str, float] = {}
        self._entry_price: dict[str, float] = {}
        self._stop_levels: dict[str, float] = {}
        self._targets: dict[str, float] = {}
        try:
            from engine import metrics as MET

            self._metrics = MET
        except ImportError:
            self._metrics = MET
        except ImportError:
            self._metrics = None
        self._registered_symbols: set[str] = set()

    # --- public API ---
    async def handle_tick(self, symbol: str, price: float, ts: float) -> dict[str, float | str] | None:
        if not self.enabled:
            return None
        base = symbol.split(".")[0].upper()
        allowed = self._universe.get("trend")
        if allowed is not None and base not in allowed:
            return None

        now = float(ts)
        if self._state[base] == "COOLDOWN" and now >= self._cooldown_until.get(base, 0.0):
            self._state[base] = "FLAT"
        if self._state[base] == "FLAT" and now < self._cooldown_until.get(base, 0.0):
            return None

        # --- Dynamic Parameter Adaptation (Micro Brain) ---
        # --- Dynamic Parameter Adaptation (Micro Brain) ---
        if base not in self._registered_symbols:
            try:
                from engine.services.param_client import get_param_client
                client = get_param_client()
                if client:
                    client.register_symbol("trend_strategy", base)
                    self._registered_symbols.add(base)
            except ImportError:
                pass

        try:
            from engine.services.param_client import apply_dynamic_config, update_context

            # 1. Calculate Features
            feats = {}
            regime_info = policy_hmm.get_regime(base)
            if regime_info:
                feats["hmm_bull"] = float(regime_info.get("p_bull", 0.0))
                feats["hmm_bear"] = float(regime_info.get("p_bear", 0.0))

            # 2. Update Context
            update_context("trend_strategy", base, feats)

            # 3. Apply Dynamic Config
            apply_dynamic_config(self, base)

        except ImportError:
            pass
        except Exception as exc:
            pass  # Fail safe

        snap = await self._build_snapshot(base)
        if snap is None:
            return None

        action: dict[str, float | str | dict[str, float | str]] | None = None
        meta: dict[str, float | str] = {
            "primary_fast": snap["primary_fast"],
            "primary_slow": snap["primary_slow"],
            "rsi": snap["rsi_primary"],
            "atr": snap["atr"],
            "regime_fast": snap["regime_fast"],
            "regime_slow": snap["regime_slow"],
        }

        if self._state[base] == "FLAT":
            if self._long_entry_ready(snap):
                stop = snap.get("stop")
                target = snap.get("target")
                atr = snap.get("atr")
                if stop is None or target is None or atr is None:
                    return None
                quote = self._quote_size(price)
                if quote <= 0:
                    return None

                # HMM Gating
                regime_info = policy_hmm.get_regime(base)
                if regime_info:
                    regime = regime_info.get("regime", "CHOP")
                    conf = regime_info.get("conf", 0.0)
                    meta["hmm_regime"] = regime
                    meta["hmm_conf"] = conf

                    # If Bearish, skip Longs
                    if regime == "BEAR" and conf > 0.5:
                        return None

                    # If Choppy, reduce size
                    if regime == "CHOP":
                        quote *= 0.5
                        meta["hmm_throttle"] = 0.5

                self._state[base] = "LONG_ACTIVE"
                self._entry_quote[base] = quote
                self._entry_price[base] = price
                self._stop_levels[base] = float(stop)
                self._targets[base] = float(target)
                meta.update({"stop": float(stop), "target": float(target), "atr": float(atr)})
                stop_bps = self._stop_distance_bps(price, float(stop))
                self._observe_stop_distance(base, stop_bps)
                self._record_signal(base, "BUY", "entry")
                market_choice = resolve_market_choice(self._qualify(base), self._default_market)
                action = {
                    "symbol": self._qualify(base),
                    "side": "BUY",
                    "quote": quote,
                    "tag": "trend_follow_long",
                    "meta": meta,
                    "market": market_choice,
                }
        elif self._state[base] == "LONG_ACTIVE":
            stop = snap.get("stop")
            target = snap.get("target")
            if stop is not None:
                self._stop_levels[base] = max(self._stop_levels.get(base, float(stop)), float(stop))
            if target is not None:
                self._targets[base] = float(target)
            meta.update({"stop": self._stop_levels.get(base), "target": self._targets.get(base)})
            if self._long_exit_ready(price, snap):
                quote = max(self._entry_quote.get(base, 0.0), self.cfg.min_quote_usd)
                self._state[base] = "COOLDOWN"
                self._cooldown_until[base] = now + self._cooldown_horizon()
                pnl_pct = 0.0
                entry_px = self._entry_price.pop(base, None)
                if entry_px and entry_px > 0:
                    pnl_pct = ((price - entry_px) / entry_px) * 100.0
                stop_value = self._stop_levels.get(base)
                stop_bps = self._stop_distance_bps(entry_px or price, stop_value)
                self._record_trade(base, pnl_pct, stop_bps, meta.copy())
                self._record_signal(base, "SELL", "exit")
                meta["pnl_pct"] = pnl_pct
                self._entry_quote.pop(base, None)
                self._stop_levels.pop(base, None)
                self._targets.pop(base, None)
                market_choice = resolve_market_choice(self._qualify(base), self._default_market)
                action = {
                    "symbol": self._qualify(base),
                    "side": "SELL",
                    "quote": quote,
                    "tag": "trend_follow_exit",
                    "meta": meta,
                    "market": market_choice,
                }

        if action and "meta" in action:
            try:
                self._log.info("[TREND] %s %s meta=%s", base, action["side"], action["meta"])
            except Exception as exc:
                pass
        return action

    # --- helpers ---
    def _qualify(self, base: str) -> str:
        return f"{base}.{self._venue}"

    def _cooldown_horizon(self) -> float:
        base_tf = _TIMEFRAME_SECONDS.get(self.cfg.primary.interval, self.cfg.refresh_sec)
        return float(max(1, int(self._params.cooldown_bars)) * base_tf)

    def _quote_size(self, price: float) -> float:
        equity = self._equity_snapshot()
        if equity <= 0.0:
            equity = self.cfg.fallback_equity_usd
        quote = max(self.cfg.min_quote_usd, equity * self.cfg.risk_pct)
        # price guard so notional respects min notional
        if price <= 0:
            return quote
        notional = max(quote, price * 0.0001)
        return round(notional, 2)

    def _equity_snapshot(self) -> float:
        try:
            from engine.core import order_router

            snap = order_router.portfolio_snapshot()
            if isinstance(snap, dict):
                equity = snap.get("equity") or snap.get("cash") or 0.0
                return float(equity or 0.0)
        except Exception as exc:
            return 0.0
        return 0.0

    def _long_entry_ready(self, snap: dict[str, float]) -> bool:
        fast = snap.get("primary_fast")
        slow = snap.get("primary_slow")
        sec_fast = snap.get("secondary_fast")
        sec_slow = snap.get("secondary_slow")
        regime_fast = snap.get("regime_fast")
        regime_slow = snap.get("regime_slow")
        rsi = snap.get("rsi_primary")
        atr = snap.get("atr")
        stop = snap.get("stop")
        target = snap.get("target")
        if None in (
            fast,
            slow,
            sec_fast,
            sec_slow,
            regime_fast,
            regime_slow,
            rsi,
            atr,
            stop,
            target,
        ):
            return False
        if fast <= slow:
            return False
        if sec_fast <= sec_slow:
            return False
        if regime_fast <= regime_slow:
            return False
        if not (self._params.rsi_long_min <= rsi <= self._params.rsi_long_max):
            return False
        return True

    def _long_exit_ready(self, price: float, snap: dict[str, float]) -> bool:
        rsi = snap.get("rsi_primary")
        fast = snap.get("primary_fast")
        slow = snap.get("primary_slow")
        if rsi is not None and rsi >= self._params.rsi_exit:
            return True
        if fast is not None and slow is not None and fast <= slow:
            return True
        guard = self._stop_levels.get(snap["symbol"])
        if guard is None:
            guard = snap.get("stop")
        if guard is not None and price <= guard:
            return True
        return False

    def _record_signal(self, symbol: str, side: str, state: str) -> None:
        if not self._metrics:
            return
        try:
            self._metrics.trend_follow_signals_total.labels(
                symbol=symbol,
                venue=self._venue,
                side=side,
                state=state,
            ).inc()
        except Exception as exc:
            pass

    def _observe_stop_distance(self, symbol: str, distance_bps: float) -> None:
        if not self._metrics or distance_bps is None:
            return
        try:
            self._metrics.trend_follow_stop_distance_bp.labels(
                symbol=symbol, venue=self._venue
            ).observe(max(distance_bps, 0.0))
        except Exception as exc:
            pass

    def _record_trade(
        self, symbol: str, pnl_pct: float, stop_bps: float, meta: dict | None = None
    ) -> None:
        result = "breakeven"
        if pnl_pct > 0.05:
            result = "win"
        elif pnl_pct < -0.05:
            result = "loss"
        if self._metrics:
            try:
                self._metrics.trend_follow_trades_total.labels(
                    symbol=symbol, venue=self._venue, result=result
                ).inc()
                self._metrics.trend_follow_trade_pnl_pct.labels(
                    symbol=symbol, venue=self._venue, result=result
                ).observe(abs(pnl_pct))
            except Exception as exc:
                pass
        try:
            self._auto_tuner.observe_trade(symbol, pnl_pct, stop_bps, meta or {})
        except Exception as exc:
            self._log.debug("[TREND] auto tuner observe failed", exc_info=True)

    @staticmethod
    def _stop_distance_bps(price: float, stop: float) -> float:
        if price <= 0 or stop is None:
            return 0.0
        return max(0.0, (price - stop) / price * 10_000.0)

    async def _build_snapshot(self, base: str) -> dict[str, float] | None:
        primary = await self._klines(base, self.cfg.primary.interval, self._params.primary_slow + 5)
        secondary = await self._klines(base, self.cfg.secondary.interval, self._params.secondary_slow + 5)
        regime = await self._klines(base, self.cfg.regime.interval, self._params.regime_slow + 5)
        if not primary or not secondary or not regime:
            return None
        primary_closes = [float(row[4]) for row in primary]
        secondary_closes = [float(row[4]) for row in secondary]
        regime_closes = [float(row[4]) for row in regime]
        snapshot = {
            "symbol": base,
            "primary_fast": _sma(primary_closes, int(self._params.primary_fast)),
            "primary_slow": _sma(primary_closes, int(self._params.primary_slow)),
            "secondary_fast": _sma(secondary_closes, int(self._params.secondary_fast)),
            "secondary_slow": _sma(secondary_closes, int(self._params.secondary_slow)),
            "regime_fast": _sma(regime_closes, int(self._params.regime_fast)),
            "regime_slow": _sma(regime_closes, int(self._params.regime_slow)),
            "rsi_primary": _rsi(primary_closes, int(self._params.rsi_length)),
            "atr": _atr(primary, self.cfg.atr_length),
        }
        atr_val = snapshot["atr"]
        swing = _swing_low(primary, self.cfg.swing_lookback)
        if atr_val is None or swing is None:
            snapshot["stop"] = None
            snapshot["target"] = None
        else:
            snapshot["stop"] = swing - (atr_val * self._params.atr_stop_mult)
            snapshot["target"] = primary_closes[-1] + (atr_val * self._params.atr_target_mult)
        return snapshot

    async def _klines(self, base: str, interval: str, minimum: int) -> list[list[float]] | None:
        key = (base, interval)
        now = self._clock.time()
        cached = self._cache.get(base, {}).get(interval)
        if cached and now - self._last_fetch[key] < self.cfg.refresh_sec:
            return cached
        data: list[list[float]] | None = None
        try:
            data = await self._client.klines(
                base, interval=interval, limit=max(self.cfg.fetch_limit, minimum)
            )
        except Exception as exc:
            self._log.warning("[TREND] kline fetch failed for %s %s: %s", base, interval, exc)
            data = None
        if isinstance(data, list) and len(data) >= minimum:
            self._cache[base][interval] = data
            self._last_fetch[key] = now
            return data
        return cached


class _AsyncKlinesClient:
    def __init__(self):
        settings = get_settings()
        base = getattr(settings, "base_url", "https://api.binance.com") or "https://api.binance.com"
        self._base = base.rstrip("/")
        self._timeout = getattr(settings, "timeout", 10.0)
        self._headers = {}
        api_key = getattr(settings, "api_key", "")
        if api_key:
            self._headers["X-MBX-APIKEY"] = api_key
        self._is_futures = getattr(settings, "is_futures", False)
        # We use a single client for efficiency (managed externally or here)
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def klines(self, symbol: str, *, interval: str, limit: int) -> list[list[float]]:
        path = "/fapi/v1/klines" if self._is_futures else "/api/v3/klines"
        try:
            resp = await self._client.get(
                f"{self._base}{path}",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                headers=self._headers or None,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            raise


__all__ = ["TrendStrategyModule", "TrendStrategyConfig", "load_trend_config"]
