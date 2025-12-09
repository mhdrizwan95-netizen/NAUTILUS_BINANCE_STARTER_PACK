from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from engine.config import get_settings
from engine.config.defaults import GLOBAL_DEFAULTS, SYMBOL_SCANNER_DEFAULTS
from engine.config.env import env_bool, env_float, env_int, env_str, split_symbols

_SUPPRESSIBLE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    KeyError,
    httpx.HTTPError,
)


@dataclass
class SymbolScannerConfig:
    enabled: bool
    universe: Sequence[str]
    interval_sec: int
    interval: str
    lookback: int
    top_n: int
    min_volume_usd: float
    min_atr_pct: float
    weight_return: float
    weight_trend: float
    weight_vol: float
    min_minutes_between_select: int
    state_path: str


def load_symbol_scanner_config() -> SymbolScannerConfig:
    universe_raw = env_str(
        "SYMBOL_SCANNER_UNIVERSE", SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_UNIVERSE"]
    ).strip()
    if universe_raw in {"", "*"}:
        fallback = (
            split_symbols(env_str("TRADE_SYMBOLS", GLOBAL_DEFAULTS["TRADE_SYMBOLS"]) or None) or []
        )
        universe = fallback or ["BTCUSDT", "ETHUSDT"]
    elif "," in universe_raw:
        parsed = split_symbols(universe_raw)
        universe = parsed or ["BTCUSDT", "ETHUSDT"]
    else:
        universe = [universe_raw.upper()]
    return SymbolScannerConfig(
        enabled=env_bool(
            "SYMBOL_SCANNER_ENABLED", SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_ENABLED"]
        ),
        universe=universe,
        interval_sec=env_int(
            "SYMBOL_SCANNER_INTERVAL_SEC",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_INTERVAL_SEC"],
        ),
        interval=env_str(
            "SYMBOL_SCANNER_INTERVAL",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_INTERVAL"],
        ),
        lookback=env_int(
            "SYMBOL_SCANNER_LOOKBACK",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_LOOKBACK"],
        ),
        top_n=env_int("SYMBOL_SCANNER_TOP_N", SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_TOP_N"]),
        min_volume_usd=env_float(
            "SYMBOL_SCANNER_MIN_VOLUME_USD",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_MIN_VOLUME_USD"],
        ),
        min_atr_pct=env_float(
            "SYMBOL_SCANNER_MIN_ATR_PCT",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_MIN_ATR_PCT"],
        ),
        weight_return=env_float(
            "SYMBOL_SCANNER_WEIGHT_RET",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_WEIGHT_RET"],
        ),
        weight_trend=env_float(
            "SYMBOL_SCANNER_WEIGHT_TREND",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_WEIGHT_TREND"],
        ),
        weight_vol=env_float(
            "SYMBOL_SCANNER_WEIGHT_VOL",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_WEIGHT_VOL"],
        ),
        min_minutes_between_select=env_int(
            "SYMBOL_SCANNER_MIN_MINUTES_BETWEEN_RESELECT",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_MIN_MINUTES_BETWEEN_RESELECT"],
        ),
        state_path=env_str(
            "SYMBOL_SCANNER_STATE_PATH",
            SYMBOL_SCANNER_DEFAULTS["SYMBOL_SCANNER_STATE_PATH"],
        ),
    )


class SymbolScanner:
    def __init__(self, cfg: SymbolScannerConfig):
        self.cfg = cfg
        self._selected: list[str] = list(cfg.universe[: cfg.top_n])
        self._scores: dict[str, float] = {}
        self._last_selected: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._base_url = (get_settings().base_url or "https://api.binance.com").rstrip("/")
        self._futures_base_url = (get_settings().futures_base or "https://fapi.binance.com").rstrip("/")
        self._universe_size = 20  # How many top coins to consider as universe
        self._dynamic_universe: list[str] = []  # Cached dynamic universe
        self._universe_refresh_interval = 3600  # Refresh universe every hour
        self._last_universe_refresh = 0.0
        self._state_path = Path(self.cfg.state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        try:
            from engine import metrics as MET
            self._metrics = MET
        except ImportError:
            self._metrics = None

        # Register for Dynamic Params (Macro Brain)
        try:
            from engine.services.param_client import get_param_client
            client = get_param_client()
            if client:
                client.register_symbol("symbol_scanner", "GLOBAL")
        except ImportError:
            pass

    def _fetch_dynamic_universe(self) -> list[str]:
        """
        Fetch top N USDT perpetual futures by 24h volume from Binance.
        Returns list of symbols like ['BTCUSDT', 'ETHUSDT', ...].
        Falls back to config universe on error.
        """
        now = time.time()
        
        # Use cached universe if still fresh
        if self._dynamic_universe and (now - self._last_universe_refresh) < self._universe_refresh_interval:
            return self._dynamic_universe
        
        try:
            # Fetch 24hr ticker data from Binance Futures
            url = f"{self._futures_base_url}/fapi/v1/ticker/24hr"
            resp = httpx.get(url, timeout=15.0)
            resp.raise_for_status()
            tickers = resp.json()
            
            if not isinstance(tickers, list):
                raise ValueError("Invalid ticker response")
            
            # Filter USDT perpetuals and sort by quote volume
            usdt_pairs = []
            for t in tickers:
                symbol = t.get("symbol", "")
                # Only USDT pairs, exclude stablecoins and low-liquidity pairs
                if not symbol.endswith("USDT"):
                    continue
                if any(skip in symbol for skip in ["BUSD", "TUSD", "USDCUSDT", "DAIUSDT", "FDUSD"]):
                    continue
                    
                try:
                    quote_volume = float(t.get("quoteVolume", 0))
                except (ValueError, TypeError):
                    continue
                    
                usdt_pairs.append((symbol, quote_volume))
            
            # Sort by volume descending and take top N
            usdt_pairs.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [sym for sym, _ in usdt_pairs[:self._universe_size]]
            
            if top_symbols:
                self._dynamic_universe = top_symbols
                self._last_universe_refresh = now
                logging.getLogger(__name__).info(f"Dynamic Universe Fetched ({len(top_symbols)}): {top_symbols[:3]}...")
                return top_symbols
                
        except _SUPPRESSIBLE_EXCEPTIONS as e:
            logging.getLogger(__name__).warning(f"Failed to fetch dynamic universe: {e}")
        
        # Fallback to config universe
        logging.getLogger(__name__).info("Using fallback config universe")
        return list(self.cfg.universe)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="symbol-scanner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def get_selected(self) -> list[str]:
        with self._lock:
            return list(self._selected)

    # ------------------------------------------------------------------ compatibility helpers
    def current_universe(self, strategy: str | None = None) -> list[str]:
        """Return the currently selected universe for ``strategy``.

        The current implementation does not differentiate by strategy and simply
        returns the global shortlist. The ``strategy`` parameter is accepted to
        support the ``StrategyUniverse`` adapter which may request per-strategy
        universes in the future.
        """

        return self.get_selected()

    def is_selected(self, symbol: str) -> bool:
        base = symbol.split(".")[0].upper()
        with self._lock:
            return base in self._selected

    # --- internal ---
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_once()
            except _SUPPRESSIBLE_EXCEPTIONS:
                pass
            self._stop.wait(self.cfg.interval_sec)

    def _scan_once(self) -> None:
        ranked: list[tuple[str, float]] = []
        now = time.time()
        logger = logging.getLogger(__name__)

        # --- Dynamic Parameter Adaptation (Macro Brain) ---
        try:
            from engine.services.param_client import apply_dynamic_config, update_context

            # 1. Calculate Global Features (e.g. BTC Volatility)
            btc_vol = 0.0
            btc_data = self._fetch_klines("BTCUSDT")
            if btc_data:
                closes = [float(row[4]) for row in btc_data]
                highs = [float(row[2]) for row in btc_data]
                lows = [float(row[3]) for row in btc_data]
                atr = self._atr(highs, lows, closes)
                if closes and closes[-1] > 0:
                    btc_vol = atr / closes[-1]

            # 2. Update Context
            update_context("symbol_scanner", "GLOBAL", {"btc_vol": btc_vol})

            # 3. Apply Dynamic Config
            apply_dynamic_config(self, "GLOBAL")

        except ImportError:
            pass
        except Exception:
            pass  # Fail safe

        # Fetch dynamic universe (top coins by volume)
        universe = self._fetch_dynamic_universe()
        
        for sym in universe:
            if self._cooldown_active(sym, now):
                continue
            # Optimization: If we already fetched BTC, reuse it?
            # But simpler to just fetch again or rely on cache if implemented (no cache in _fetch_klines)
            # Given lookback is small, it's fine.
            data = self._fetch_klines(sym)
            if not data:
                logger.debug(f"No kline data for {sym}")
                continue
            score = self._score_symbol(sym, data)
            if score is None:
                logger.debug(f"Score None for {sym} (filtered)")
                continue
            ranked.append((sym, score))
            
        ranked.sort(key=lambda x: x[1], reverse=True)
        top = [sym for sym, _ in ranked[: self.cfg.top_n]]
        
        if top:
            logger.info(f"Scanner Selected: {top} (from {len(ranked)} ranked)")
        else:
            logger.warning("Scanner selected EMPTY set! Keeping previous.")

        # Log dynamic weights if top changed or periodically?
        # Let's just log if we have a logger. SymbolScanner doesn't have self._log.
        # I'll add logging import and use module level logger or print.

        with self._lock:
            self._selected = top or list(self._selected)
            for sym, score in ranked:
                self._scores[sym] = score
                self._set_metric(sym, score)
            for sym in top:
                self._last_selected[sym] = now
                self._inc_selected(sym)
        self._persist_state()

    def _fetch_klines(self, symbol: str) -> list[list[str]] | None:
        # Use Futures API for klines as we are in Futures mode
        url = f"{self._futures_base_url}/fapi/v1/klines"
        try:
            resp = httpx.get(
                url,
                params={
                    "symbol": symbol,
                    "interval": self.cfg.interval,
                    "limit": self.cfg.lookback,
                },
                timeout=10.0,
            )

            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data
        except _SUPPRESSIBLE_EXCEPTIONS:
            return None
        return None

    def _score_symbol(self, symbol: str, klines: list[list[str]]) -> float | None:
        try:
            closes = [float(row[4]) for row in klines]
            highs = [float(row[2]) for row in klines]
            lows = [float(row[3]) for row in klines]
            vols = [float(row[5]) for row in klines]
            if not closes or len(closes) < 5:
                return None
            ret = (closes[-1] / closes[0]) - 1.0
            fast = sum(closes[-5:]) / min(5, len(closes))
            slow = sum(closes) / len(closes)
            trend = (fast / slow) - 1.0 if slow else 0.0
            atr = self._atr(highs, lows, closes)
            atr_pct = atr / closes[-1] * 100.0 if closes[-1] else 0.0
            volume_usd = sum(vols) / len(vols) * closes[-1]
            if volume_usd < self.cfg.min_volume_usd:
                return None
            if atr_pct < self.cfg.min_atr_pct:
                return None
            score = (
                ret * self.cfg.weight_return
                + trend * self.cfg.weight_trend
                + atr_pct / 100.0 * self.cfg.weight_vol
            )
        except _SUPPRESSIBLE_EXCEPTIONS:
            return None
        else:
            return round(score, 6)

    def _atr(self, highs: list[float], lows: list[float], closes: list[float]) -> float:
        if len(highs) < 2:
            return 0.0
        trs = []
        prev_close = closes[0]
        for high, low, close in zip(highs[1:], lows[1:], closes[1:], strict=False):
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        return sum(trs) / len(trs) if trs else 0.0

    def _cooldown_active(self, symbol: str, now: float) -> bool:
        cooldown = self.cfg.min_minutes_between_select * 60
        last = self._last_selected.get(symbol)
        if not last:
            return False
        return (now - last) < cooldown

    def _set_metric(self, symbol: str, score: float) -> None:
        if not self._metrics:
            return
        try:
            self._metrics.symbol_scanner_score.labels(symbol=symbol).set(score)
        except _SUPPRESSIBLE_EXCEPTIONS:
            pass

    def _inc_selected(self, symbol: str) -> None:
        if not self._metrics:
            return
        try:
            self._metrics.symbol_scanner_selected_total.labels(symbol=symbol).inc()
        except _SUPPRESSIBLE_EXCEPTIONS:
            pass

    def _persist_state(self) -> None:
        payload = {
            "selected": self._selected,
            "scores": self._scores,
            "last_selected": self._last_selected,
        }
        try:
            self._state_path.write_text(json.dumps(payload, indent=2))
        except _SUPPRESSIBLE_EXCEPTIONS:
            pass

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
            self._selected = list(data.get("selected") or self._selected)
            self._scores = data.get("scores") or {}
            self._last_selected = data.get("last_selected") or {}
        except _SUPPRESSIBLE_EXCEPTIONS:
            pass


__all__ = ["SymbolScanner", "SymbolScannerConfig", "load_symbol_scanner_config"]
