from __future__ import annotations

"""High-frequency scalping module driven by streaming market data."""

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Optional, TYPE_CHECKING

from engine import metrics
from engine.config.defaults import SCALP_DEFAULTS
from engine.config.env import env_bool, env_float, env_int
from engine.core.market_resolver import resolve_market_choice
from engine.universe.effective import StrategyUniverse
from engine.state.cooldown import Cooldowns

try:  # Optional dependency used for realistic slippage estimation
    from ops import slip_model as _slip_module  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    _slip_module = None  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    from .symbol_scanner import SymbolScanner


@dataclass(frozen=True)
class ScalpConfig:
    enabled: bool
    dry_run: bool
    symbols: tuple[str, ...]
    window_sec: float
    min_ticks: int
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
    prefer_futures: bool
    signal_ttl_sec: float
    max_signals_per_min: int
    imbalance_threshold: float
    max_spread_bps: float
    min_depth_usd: float
    momentum_ticks: int
    fee_bps: float
    book_stale_sec: float


def load_scalp_config(scanner: "SymbolScanner" | None = None) -> ScalpConfig:
    universe = StrategyUniverse(scanner).get("scalp") or []
    symbols = tuple(universe)
    window = max(5.0, env_float("SCALP_WINDOW_SEC", SCALP_DEFAULTS["SCALP_WINDOW_SEC"]))
    return ScalpConfig(
        enabled=env_bool("SCALP_ENABLED", SCALP_DEFAULTS["SCALP_ENABLED"]),
        dry_run=env_bool("SCALP_DRY_RUN", SCALP_DEFAULTS["SCALP_DRY_RUN"]),
        symbols=symbols,
        window_sec=window,
        min_ticks=max(3, env_int("SCALP_MIN_TICKS", SCALP_DEFAULTS["SCALP_MIN_TICKS"])),
        min_range_bps=max(
            3.0, env_float("SCALP_MIN_RANGE_BPS", SCALP_DEFAULTS["SCALP_MIN_RANGE_BPS"])
        ),
        lower_threshold=min(
            0.45,
            max(
                0.0,
                env_float("SCALP_LOWER_THRESHOLD", SCALP_DEFAULTS["SCALP_LOWER_THRESHOLD"]),
            ),
        ),
        upper_threshold=max(
            0.55,
            min(
                1.0,
                env_float("SCALP_UPPER_THRESHOLD", SCALP_DEFAULTS["SCALP_UPPER_THRESHOLD"]),
            ),
        ),
        rsi_length=max(2, env_int("SCALP_RSI_LENGTH", SCALP_DEFAULTS["SCALP_RSI_LENGTH"])),
        rsi_buy=max(0.0, env_float("SCALP_RSI_BUY", SCALP_DEFAULTS["SCALP_RSI_BUY"])),
        rsi_sell=min(100.0, env_float("SCALP_RSI_SELL", SCALP_DEFAULTS["SCALP_RSI_SELL"])),
        stop_bps=max(4.0, env_float("SCALP_STOP_BPS", SCALP_DEFAULTS["SCALP_STOP_BPS"])),
        take_profit_bps=max(4.0, env_float("SCALP_TP_BPS", SCALP_DEFAULTS["SCALP_TP_BPS"])),
        quote_usd=max(10.0, env_float("SCALP_QUOTE_USD", SCALP_DEFAULTS["SCALP_QUOTE_USD"])),
        cooldown_sec=max(
            0.0, env_float("SCALP_COOLDOWN_SEC", SCALP_DEFAULTS["SCALP_COOLDOWN_SEC"])
        ),
        allow_shorts=env_bool("SCALP_ALLOW_SHORTS", SCALP_DEFAULTS["SCALP_ALLOW_SHORTS"]),
        prefer_futures=env_bool("SCALP_PREFER_FUTURES", SCALP_DEFAULTS["SCALP_PREFER_FUTURES"]),
        signal_ttl_sec=max(
            5.0,
            env_float("SCALP_SIGNAL_TTL_SEC", SCALP_DEFAULTS["SCALP_SIGNAL_TTL_SEC"]),
        ),
        max_signals_per_min=max(
            1,
            env_int("SCALP_MAX_SIGNALS_PER_MIN", SCALP_DEFAULTS["SCALP_MAX_SIGNALS_PER_MIN"]),
        ),
        imbalance_threshold=max(
            0.0,
            min(
                1.0,
                env_float(
                    "SCALP_IMBALANCE_THRESHOLD",
                    SCALP_DEFAULTS["SCALP_IMBALANCE_THRESHOLD"],
                ),
            ),
        ),
        max_spread_bps=max(
            1.0,
            env_float("SCALP_MAX_SPREAD_BPS", SCALP_DEFAULTS["SCALP_MAX_SPREAD_BPS"]),
        ),
        min_depth_usd=max(
            1000.0,
            env_float("SCALP_MIN_DEPTH_USD", SCALP_DEFAULTS["SCALP_MIN_DEPTH_USD"]),
        ),
        momentum_ticks=max(
            1, env_int("SCALP_MOMENTUM_TICKS", SCALP_DEFAULTS["SCALP_MOMENTUM_TICKS"])
        ),
        fee_bps=max(0.0, env_float("SCALP_FEE_BPS", SCALP_DEFAULTS["SCALP_FEE_BPS"])),
        book_stale_sec=max(
            1.0,
            env_float("SCALP_BOOK_STALE_SEC", SCALP_DEFAULTS["SCALP_BOOK_STALE_SEC"]),
        ),
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


@dataclass
class _BookState:
    ts: float
    bid_price: float
    ask_price: float
    bid_qty: float
    ask_qty: float

    @property
    def mid(self) -> float:
        if self.bid_price <= 0.0 or self.ask_price <= 0.0:
            return 0.0
        return (self.bid_price + self.ask_price) / 2.0

    @property
    def spread_bp(self) -> float:
        mid = self.mid
        if mid <= 0.0:
            return 0.0
        spread = max(0.0, self.ask_price - self.bid_price)
        return (spread / mid) * 10_000.0

    @property
    def imbalance(self) -> float:
        bid = max(self.bid_qty, 0.0)
        ask = max(self.ask_qty, 0.0)
        denom = bid + ask
        if denom <= 0.0:
            return 0.0
        return (bid - ask) / denom

    @property
    def depth_usd(self) -> float:
        bid = max(self.bid_qty, 0.0) * max(self.bid_price, 0.0)
        ask = max(self.ask_qty, 0.0) * max(self.ask_price, 0.0)
        return bid + ask


class ScalpStrategyModule:
    """Reactive scalping strategy operating on streaming tick + book data."""

    def __init__(
        self,
        cfg: Optional[ScalpConfig] = None,
        *,
        clock=time,
        slip_predictor: Optional[Callable[[Dict[str, float]], float]] = None,
        scanner: "SymbolScanner" | None = None,
    ) -> None:
        base_cfg = cfg or load_scalp_config(scanner)
        self.cfg = base_cfg
        self.enabled = self.cfg.enabled
        self._clock = clock
        self._windows: Dict[str, Deque[tuple[float, float]]] = defaultdict(deque)
        self._books: Dict[str, _BookState] = {}
        self._cooldowns = Cooldowns(default_ttl=self.cfg.cooldown_sec)
        self._signal_history: Dict[str, Deque[float]] = defaultdict(deque)
        self._slip_predictor = slip_predictor or self._load_slip_predictor()
        self._universe = StrategyUniverse(scanner)

    def _load_slip_predictor(self) -> Optional[Callable[[Dict[str, float]], float]]:
        if not _slip_module:
            return None
        try:
            model = _slip_module.load_model()
        except Exception:  # pragma: no cover - best effort
            return None
        if not model:
            return None

        def _predict(features: Dict[str, float]) -> float:
            try:
                return float(_slip_module.predict_slip_bp(model, features))
            except Exception:
                return 0.0

        return _predict

    def _book_for(self, base: str, now: float) -> Optional[_BookState]:
        book = self._books.get(base)
        if not book:
            return None
        if now - book.ts > self.cfg.book_stale_sec:
            return None
        return book

    def handle_book(
        self,
        symbol: str,
        bid_price: float,
        ask_price: float,
        bid_qty: float,
        ask_qty: float,
        ts: Optional[float] = None,
    ) -> None:
        if not self.enabled:
            return
        if not symbol:
            return
        base = symbol.split(".")[0].upper()
        allowed = self._universe.get("scalp")
        if allowed is not None and base not in allowed:
            return
        now = ts if ts is not None else self._clock.time()
        book = _BookState(
            ts=float(now),
            bid_price=float(bid_price or 0.0),
            ask_price=float(ask_price or 0.0),
            bid_qty=float(bid_qty or 0.0),
            ask_qty=float(ask_qty or 0.0),
        )
        self._books[base] = book
        venue = symbol.split(".")[1].lower() if "." in symbol else "binance"
        try:
            metrics.scalp_spread_bp.labels(symbol=base, venue=venue).set(book.spread_bp)
            metrics.scalp_orderbook_imbalance.labels(symbol=base, venue=venue).set(book.imbalance)
        except Exception:
            pass

    def _estimate_slippage_bp(self, features: Dict[str, float]) -> float:
        predictor = self._slip_predictor
        if not predictor:
            return 0.0
        return float(predictor(features))

    def _slip_features(self, book: _BookState, *, side: str, range_bps: float) -> Dict[str, float]:
        return {
            "spread_bp": max(book.spread_bp, 0.0),
            "depth_imbalance": book.imbalance,
            "depth_usd": max(book.depth_usd, 0.0),
            "atrp_1m": max(range_bps, 0.0),
            "order_quote_usd": float(self.cfg.quote_usd),
            "is_burst": 1.0 if range_bps >= (self.cfg.min_range_bps * 1.8) else 0.0,
            "side": 1.0 if side == "BUY" else -1.0,
        }

    def _record_signal_metrics(
        self,
        *,
        base: str,
        venue: str,
        side: str,
        reason: str,
        ttl: float,
        edge_bp: float,
        slip_bp: float,
    ) -> None:
        try:
            metrics.scalp_signals_total.labels(
                symbol=base,
                venue=venue,
                side=side,
                reason=reason,
            ).inc()
            metrics.scalp_signal_ttl_sec.labels(symbol=base, venue=venue, side=side).set(ttl)
            metrics.scalp_signal_edge_bp.labels(symbol=base, venue=venue, side=side).set(edge_bp)
            metrics.scalp_slippage_estimate_bp.labels(symbol=base, venue=venue, side=side).set(
                slip_bp
            )
        except Exception:
            pass

    def handle_tick(self, symbol: str, price: float, ts: float) -> Optional[dict]:
        if not self.enabled or price <= 0.0 or not math.isfinite(price):
            return None
        if not symbol:
            return None

        base = symbol.split(".")[0].upper()
        venue = symbol.split(".")[1].lower() if "." in symbol else "binance"
        allowed = self._universe.get("scalp")
        if allowed is not None and base not in allowed:
            return None

        now = ts if ts is not None else self._clock.time()
        window = self._windows[base]
        window.append((now, float(price)))
        cutoff = now - self.cfg.window_sec
        while window and window[0][0] < cutoff:
            window.popleft()
        if len(window) < self.cfg.min_ticks:
            return None

        prices = [p for _, p in window]
        low = min(prices)
        high = max(prices)
        span = high - low
        if span <= 0.0:
            return None
        range_bps = (span / price) * 10_000.0 if price > 0 else 0.0
        if range_bps < self.cfg.min_range_bps:
            return None

        book = self._book_for(base, now)
        if not book or book.spread_bp > self.cfg.max_spread_bps:
            return None
        if book.depth_usd < self.cfg.min_depth_usd:
            return None

        price_pos = (price - low) / span if span > 0 else 0.5
        rsi_value = _rsi(prices, self.cfg.rsi_length)

        momentum_idx = min(self.cfg.momentum_ticks, len(prices) - 1)
        prev_price = prices[-momentum_idx - 1] if momentum_idx < len(prices) else prices[0]
        momentum = price - prev_price

        try:
            metrics.scalp_range_width_bp.labels(symbol=base, venue=venue).set(range_bps)
            metrics.scalp_position.labels(symbol=base, venue=venue).set(price_pos)
            if rsi_value is not None:
                metrics.scalp_rsi.labels(symbol=base, venue=venue).set(rsi_value)
        except Exception:
            pass

        history = self._signal_history[base]
        cutoff_rate = now - 60.0
        while history and history[0] < cutoff_rate:
            history.popleft()
        if len(history) >= self.cfg.max_signals_per_min:
            return None

        if not self._cooldowns.allow(base, now=now):
            return None

        side: Optional[str] = None
        reason = ""
        imbalance = book.imbalance

        bullish_flow = imbalance >= self.cfg.imbalance_threshold or (momentum > 0)
        bearish_flow = -imbalance >= self.cfg.imbalance_threshold or (momentum < 0)
        oversold = rsi_value is not None and rsi_value <= self.cfg.rsi_buy
        overbought = rsi_value is not None and rsi_value >= self.cfg.rsi_sell

        if price_pos <= self.cfg.lower_threshold and (bullish_flow or oversold):
            side = "BUY"
            reason = "range_support" if bullish_flow else "rsi_rebound"
        elif (
            self.cfg.allow_shorts
            and price_pos >= self.cfg.upper_threshold
            and (bearish_flow or overbought)
            and not oversold
        ):
            side = "SELL"
            reason = "range_resist" if bearish_flow else "rsi_mean_revert"

        if side is None:
            return None

        slip_features = self._slip_features(book, side=side, range_bps=range_bps)
        slip_bp = max(0.0, self._estimate_slippage_bp(slip_features))
        fees = self.cfg.fee_bps
        gross_edge = self.cfg.take_profit_bps
        net_edge = gross_edge - slip_bp - fees
        if net_edge <= 0.0:
            return None

        stop_factor = self.cfg.stop_bps / 10_000.0
        tp_factor = self.cfg.take_profit_bps / 10_000.0
        if side == "BUY":
            stop_price = price * (1.0 - stop_factor)
            target_price = price * (1.0 + tp_factor)
        else:
            stop_price = price * (1.0 + stop_factor)
            target_price = price * (1.0 - tp_factor)

        ttl = self.cfg.signal_ttl_sec
        expires_at = now + ttl

        self._cooldowns.hit(base, now=now)
        history.append(now)

        self._record_signal_metrics(
            base=base,
            venue=venue,
            side=side,
            reason=reason,
            ttl=ttl,
            edge_bp=net_edge,
            slip_bp=slip_bp,
        )

        market_pref = "futures" if (self.cfg.prefer_futures or side == "SELL") else "spot"
        market_choice = resolve_market_choice(symbol, market_pref)
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
                "signal_expires_at": expires_at,
                "order_book_imbalance": imbalance,
                "spread_bp": book.spread_bp,
                "expected_edge_bp": net_edge,
                "slippage_estimate_bp": slip_bp,
            },
            "market": market_choice,
        }
