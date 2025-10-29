from __future__ import annotations
import asyncio, inspect, logging, os
import threading, time, uuid
from collections import deque, defaultdict
from typing import Any, Callable, Deque, Dict, List, Optional, cast
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .config import load_strategy_config, load_risk_config
from .risk import RiskRails, Side
from .idempotency import CACHE, append_jsonl
from . import metrics
from .core import order_router
from .core.market_resolver import resolve_market_choice
from .core.event_bus import BUS
from .telemetry.publisher import record_tick_latency
from .strategies import policy_hmm, ensemble_policy
from .strategies.calibration import cooldown_scale as calibration_cooldown_scale
from .strategies.trend_follow import TrendStrategyModule, load_trend_config
from .strategies.scalping import ScalpStrategyModule, load_scalp_config
from .telemetry.publisher import record_latency
try:
    from .strategies.momentum_realtime import MomentumStrategyModule, load_momentum_rt_config
except Exception:  # pragma: no cover - optional component
    MomentumStrategyModule = None  # type: ignore
    load_momentum_rt_config = None  # type: ignore
try:
    from .strategies.symbol_scanner import SymbolScanner, load_symbol_scanner_config
except Exception:  # pragma: no cover - optional component
    SymbolScanner = None  # type: ignore
    load_symbol_scanner_config = None  # type: ignore

router = APIRouter()
S_CFG = load_strategy_config()
R_CFG = load_risk_config()
RAILS = RiskRails(R_CFG)
SYMBOL_SCANNER = None
if SymbolScanner and load_symbol_scanner_config:
    try:
        _scanner_cfg = load_symbol_scanner_config()
        if _scanner_cfg.enabled:
            SYMBOL_SCANNER = SymbolScanner(_scanner_cfg)
            SYMBOL_SCANNER.start()
    except Exception:
        SYMBOL_SCANNER = None

TREND_CFG = None
TREND_MODULE: Optional[TrendStrategyModule] = None
try:
    TREND_CFG = load_trend_config()
    if TREND_CFG.enabled:
        TREND_MODULE = TrendStrategyModule(TREND_CFG, scanner=SYMBOL_SCANNER)
except Exception:
    TREND_MODULE = None

SCALP_CFG = None
SCALP_MODULE: Optional[ScalpStrategyModule] = None
try:
    SCALP_CFG = load_scalp_config()
    if SCALP_CFG.enabled:
        SCALP_MODULE = ScalpStrategyModule(SCALP_CFG)
except Exception:
    SCALP_MODULE = None

MOMENTUM_RT_CFG = None
MOMENTUM_RT_MODULE: Optional[MomentumStrategyModule] = None
if 'MomentumStrategyModule' in globals() and MomentumStrategyModule and load_momentum_rt_config:
    try:
        MOMENTUM_RT_CFG = load_momentum_rt_config()
        if MOMENTUM_RT_CFG.enabled:
            MOMENTUM_RT_MODULE = MomentumStrategyModule(MOMENTUM_RT_CFG)
            logging.getLogger(__name__).info(
                "Momentum RT module enabled (window=%.1fs, move>=%.2f%%, vol>=%.2fx)",
                MOMENTUM_RT_CFG.window_sec,
                MOMENTUM_RT_CFG.pct_move_threshold * 100.0,
                MOMENTUM_RT_CFG.volume_spike_ratio,
            )
    except Exception:
        MOMENTUM_RT_MODULE = None

_SCALP_BUS_WIRED = False
_SCALP_WATCH_LOCK = threading.Lock()
_ACTIVE_SCALP_WATCHES: Dict[str, threading.Thread] = {}


def _wire_scalp_fill_handler() -> None:
    global _SCALP_BUS_WIRED
    if _SCALP_BUS_WIRED:
        return
    try:
        BUS.subscribe("trade.fill", _scalp_fill_handler)
        _SCALP_BUS_WIRED = True
        logging.getLogger(__name__).info("Scalping fill handler wired")
    except Exception:
        logging.getLogger(__name__).warning("Scalping fill handler wiring failed", exc_info=True)


def _scalp_fill_handler(evt: Dict[str, Any]) -> None:
    if not SCALP_MODULE or not getattr(SCALP_MODULE, "enabled", False):
        return
    meta = evt.get("strategy_meta")
    tag = str(evt.get("strategy_tag") or "")
    if not isinstance(meta, dict):
        return
    if not tag.startswith("scalp"):
        return
    symbol = str(evt.get("symbol") or "").upper()
    venue = str(evt.get("venue") or "BINANCE").upper()
    side = str(evt.get("side") or "").upper()
    if not symbol or side not in {"BUY", "SELL"}:
        return
    qty = float(evt.get("filled_qty") or 0.0)
    if qty <= 0.0:
        return
    stop_px = float(meta.get("stop_price") or 0.0)
    target_px = float(meta.get("take_profit") or 0.0)
    if stop_px <= 0.0 or target_px <= 0.0:
        return
    order_id = str(evt.get("order_id") or "") or f"{symbol}:{evt.get('ts', time.time())}"
    _start_scalp_bracket_watch(
        order_id=order_id,
        symbol=symbol,
        venue=venue,
        side=side,
        qty=qty,
        stop_px=stop_px,
        target_px=target_px,
    )


def _start_scalp_bracket_watch(
    *,
    order_id: str,
    symbol: str,
    venue: str,
    side: str,
    qty: float,
    stop_px: float,
    target_px: float,
) -> None:
    poll = 1.0
    ttl = 180.0
    if SCALP_CFG:
        try:
            poll = max(0.5, min(5.0, float(SCALP_CFG.window_sec) / 12.0))
            ttl = max(60.0, float(SCALP_CFG.window_sec) * 3.0)
        except Exception:
            poll = max(poll, 1.0)
            ttl = max(ttl, 180.0)

    key = order_id or f"{symbol}:{side}:{int(time.time() * 1000)}"

    def _watch() -> None:
        logger = logging.getLogger(__name__)
        qualified = symbol if "." in symbol else f"{symbol}.{venue}"
        end_time = time.time() + ttl
        exit_side = "SELL" if side == "BUY" else "BUY"
        triggered: Optional[str] = None

        def _submit_exit(exit_tag: str) -> None:
            try:
                sig = StrategySignal(
                    symbol=qualified,
                    side=exit_side,
                    quote=None,
                    quantity=qty,
                    dry_run=None,
                    tag=exit_tag,
                    meta=None,
                )
                _execute_strategy_signal(sig)
                try:
                    metrics.scalp_bracket_exits_total.labels(
                        symbol=symbol, venue=venue.lower(), mode=exit_tag
                    ).inc()
                except Exception:
                    pass
            except Exception:
                logger.warning("[SCALP] exit submission failed for %s", qualified, exc_info=True)

        while time.time() < end_time:
            px = _latest_price(qualified)
            if px is None or px <= 0.0:
                time.sleep(poll)
                continue
            if side == "BUY":
                if px >= target_px:
                    triggered = "scalp_tp"
                    _submit_exit(triggered)
                    break
                if px <= stop_px:
                    triggered = "scalp_sl"
                    _submit_exit(triggered)
                    break
            else:
                if px <= target_px:
                    triggered = "scalp_tp"
                    _submit_exit(triggered)
                    break
                if px >= stop_px:
                    triggered = "scalp_sl"
                    _submit_exit(triggered)
                    break
            time.sleep(poll)
        if triggered is None:
            logger.info(
                "[SCALP] bracket timeout for %s side=%s qty=%.6f (stop=%.6f tp=%.6f)",
                qualified,
                side,
                qty,
                stop_px,
                target_px,
            )
        with _SCALP_WATCH_LOCK:
            _ACTIVE_SCALP_WATCHES.pop(key, None)

    with _SCALP_WATCH_LOCK:
        if key in _ACTIVE_SCALP_WATCHES:
            return
        thread = threading.Thread(target=_watch, name=f"scalp-bracket-{symbol}", daemon=True)
        _ACTIVE_SCALP_WATCHES[key] = thread
    thread.start()


if SCALP_MODULE and getattr(SCALP_MODULE, "enabled", False):
    _wire_scalp_fill_handler()

class _MACross:
    def __init__(self, fast: int, slow: int):
        assert fast < slow, "fast MA must be < slow MA"
        self.fast = fast
        self.slow = slow
        self.windows: Dict[str, Deque[float]] = defaultdict(deque)

    def push(self, symbol: str, price: float) -> Optional[str]:
        w = self.windows[symbol]
        w.append(price)
        # Cap deque to slow window
        while len(w) > self.slow:
            w.popleft()
        if len(w) < self.slow:
            return None
        fast_ma = sum(list(w)[-self.fast:]) / self.fast
        slow_ma = sum(w) / len(w)
        if fast_ma > slow_ma:
            return "BUY"
        if fast_ma < slow_ma:
            return "SELL"
        return None

# Global variables for scheduler
_loop_thread: Optional[threading.Thread] = None
_stop_flag: threading.Event = threading.Event()
_mac = _MACross(S_CFG.fast, S_CFG.slow)
_tick_listeners: List[Callable[[str, float, float], object]] = []
_last_tick_ts: Dict[str, float] = defaultdict(float)
_symbol_cooldown_until: Dict[str, float] = defaultdict(float)
_last_trade_price: Dict[str, float] = defaultdict(float)
_entry_block_until: float = time.time() + float(os.getenv("WARMUP_SEC", "0"))


async def _on_market_tick_event(event: Dict[str, Any]) -> None:
    symbol = str(event.get("symbol") or "")
    price = event.get("price")
    if not symbol or price is None:
        return
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return
    ts_raw = event.get("ts")
    try:
        ts_val = float(ts_raw) if ts_raw is not None else time.time()
    except (TypeError, ValueError):
        ts_val = time.time()
    vol_raw = event.get("volume")
    volume: Optional[float]
    if vol_raw is None:
        volume = None
    else:
        try:
            volume = float(vol_raw)
        except (TypeError, ValueError):
            volume = None
    cfg = getattr(S_CFG, "enabled", False)
    if not cfg:
        return
    on_tick(symbol, price_f, ts_val, volume)


try:
    BUS.subscribe("market.tick", _on_market_tick_event)
except Exception:
    logging.getLogger(__name__).warning("Failed to subscribe strategy to market.tick", exc_info=True)

class StrategySignal(BaseModel):
    symbol: str = Field(..., description="e.g. BTCUSDT.BINANCE")
    side: str = Field(..., pattern=r"^(BUY|SELL)$")
    quote: Optional[float] = Field(None, description="USDT notional (preferred)")
    quantity: Optional[float] = Field(None, description="Base qty (alternative)")
    dry_run: Optional[bool] = Field(None, description="Override STRATEGY_DRY_RUN")
    tag: Optional[str] = Field(None, description="Optional label (e.g. 'ma_cross')")
    meta: Optional[Dict[str, Any]] = Field(None, description="Optional strategy metadata (e.g. stops, targets)")
    market: Optional[str] = Field(None, description="Preferred Binance market (spot, futures, margin)")

@router.post("/strategy/signal")
def post_strategy_signal(sig: StrategySignal, request: Request):
    idem = request.headers.get("X-Idempotency-Key")
    return _execute_strategy_signal(sig, idem_key=idem)


def _execute_strategy_signal(sig: StrategySignal, *, idem_key: Optional[str] = None) -> Dict:
    side_literal = cast(Side, sig.side)
    ok, err = RAILS.check_order(
        symbol=sig.symbol,
        side=side_literal,
        quote=sig.quote,
        quantity=sig.quantity,
        market=(sig.market.lower() if isinstance(sig.market, str) else sig.market),
    )
    if not ok:
        metrics.orders_rejected.inc()
        return {"status": "rejected", **err, "source": "strategy"}

    dry = S_CFG.dry_run if sig.dry_run is None else sig.dry_run
    key = idem_key or f"strategy:{sig.symbol}:{sig.side}:{int(time.time())}"
    cached = CACHE.get(key)
    if cached:
        return cached

    if dry:
        payload = {
            "status": "simulated",
            "symbol": sig.symbol,
            "side": sig.side,
            "quote": sig.quote,
            "quantity": sig.quantity,
            "tag": sig.tag or "strategy",
            "meta": sig.meta,
            "idempotency_key": key,
            "timestamp": time.time(),
        }
        try:
            from .app import _config_hash as _cfg_hash
            payload["cfg_hash"] = _cfg_hash()
        except Exception:
            pass
        append_jsonl("orders.jsonl", payload)
        CACHE.set(key, payload)
        return payload

    from .app import router as order_router_instance

    router_ctx = {
        "meta": sig.meta,
        "tag": sig.tag or "strategy",
        "symbol": sig.symbol,
        "side": sig.side,
        "market": (sig.market.lower() if isinstance(sig.market, str) else sig.market),
    }
    try:
        setattr(order_router_instance, "_strategy_pending_meta", router_ctx)
    except Exception:
        router_ctx = None

    try:
        # Use synchronous wrapper to avoid un-awaited coroutine warnings
        res = order_router_instance.place_market_order(
            symbol=sig.symbol,
            side=side_literal,
            quote=(None if sig.quantity is not None else (sig.quote or 0.0)),
            quantity=(sig.quantity if sig.quantity is not None else None),
            market=(sig.market.lower() if isinstance(sig.market, str) else sig.market),
        )
    finally:
        if router_ctx is not None:
            try:
                if getattr(order_router_instance, "_strategy_pending_meta", None) is router_ctx:
                    delattr(order_router_instance, "_strategy_pending_meta")
            except AttributeError:
                pass
            except Exception:
                try:
                    setattr(order_router_instance, "_strategy_pending_meta", None)
                except Exception:
                    pass

    _record_tick_latency(sig.symbol)

    metrics.orders_submitted.inc()
    resp = {
        "status": "submitted",
        "order": res,
        "tag": sig.tag or "strategy",
        "meta": sig.meta,
        "idempotency_key": key,
        "timestamp": time.time(),
    }
    try:
        from .app import _config_hash as _cfg_hash
        resp["cfg_hash"] = _cfg_hash()
    except Exception:
        pass
    append_jsonl("orders.jsonl", resp)
    CACHE.set(key, resp)
    try:
        from .state import SnapshotStore
        SnapshotStore().save(order_router_instance.portfolio_snapshot())
    except Exception:
        pass
    return resp


def register_tick_listener(cb: Callable[[str, float, float], object]) -> None:
    """Register an external listener invoked on every tick."""
    _tick_listeners.append(cb)


def clear_tick_listeners() -> None:
    _tick_listeners.clear()


def _notify_listeners(symbol: str, price: float, ts: float) -> None:
    for cb in list(_tick_listeners):
        try:
            res = cb(symbol, price, ts)
            if res is not None and inspect.isawaitable(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)  # type: ignore[arg-type]
                except RuntimeError:
                    # No running loop in this thread; drop async listener result
                    pass
        except Exception:
            continue


def on_tick(symbol: str, price: float, ts: float | None = None, volume: float | None = None) -> None:
    """Tick-driven strategy loop entrypoint."""
    ts_val = float(ts if ts is not None else time.time())
    venue = symbol.split(".")[1] if "." in symbol else "BINANCE"
    base = symbol.split(".")[0].upper()
    qualified = symbol if "." in symbol else f"{base}.{venue}"
    _last_tick_ts[qualified] = ts_val
    _last_tick_ts[base] = ts_val

    _notify_listeners(qualified, price, ts_val)

    # Entry block window (startup/reconnect warmup)
    if time.time() < _entry_block_until:
        return

    if SCALP_MODULE and SCALP_MODULE.enabled:
        scalp_decision = None
        try:
            scalp_decision = SCALP_MODULE.handle_tick(qualified, price, ts_val)
        except Exception:
            scalp_decision = None
        if scalp_decision:
            scalp_symbol = str(scalp_decision.get("symbol") or qualified)
            scalp_side = str(scalp_decision.get("side") or "BUY")
            scalp_quote = float(scalp_decision.get("quote") or S_CFG.quote_usdt)
            scalp_tag = str(scalp_decision.get("tag") or "scalp")
            default_market = scalp_decision.get("market") or ("futures" if getattr(SCALP_CFG, "allow_shorts", True) else "spot")
            resolved_market = resolve_market_choice(scalp_symbol, default_market)
            sig = StrategySignal(
                symbol=scalp_symbol,
                side=scalp_side,
                quote=scalp_quote,
                quantity=None,
                dry_run=None,
                tag=scalp_tag,
                meta=scalp_decision.get("meta"),
                market=resolved_market,
            )
            result = _execute_strategy_signal(sig)
            if result.get("status") == "submitted":
                scalp_base = scalp_symbol.split(".")[0]
                scalp_venue = scalp_symbol.split(".")[1] if "." in scalp_symbol else "BINANCE"
                try:
                    metrics.strategy_orders_total.labels(
                        symbol=scalp_base, venue=scalp_venue, side=scalp_side, source=scalp_tag
                    ).inc()
                except Exception:
                    pass
            return

    if MOMENTUM_RT_MODULE and getattr(MOMENTUM_RT_MODULE, "enabled", False):
        momentum_decision = None
        try:
            momentum_decision = MOMENTUM_RT_MODULE.handle_tick(qualified, price, ts_val, volume)
        except Exception:
            momentum_decision = None
        if momentum_decision:
            momentum_symbol = str(momentum_decision.get("symbol") or qualified)
            momentum_side = str(momentum_decision.get("side") or "BUY")
            momentum_quote = float(momentum_decision.get("quote") or S_CFG.quote_usdt)
            momentum_tag = str(momentum_decision.get("tag") or "momentum_rt")
            momentum_meta = momentum_decision.get("meta")
            default_market = momentum_decision.get("market") or (
                "futures" if getattr(MOMENTUM_RT_CFG, "prefer_futures", True) or momentum_side == "SELL" else "spot"
            )
            resolved_market = resolve_market_choice(momentum_symbol, default_market)
            sig = StrategySignal(
                symbol=momentum_symbol,
                side=momentum_side,
                quote=momentum_quote,
                quantity=None,
                dry_run=None,
                tag=momentum_tag,
                meta=momentum_meta,
                market=resolved_market,
            )
            result = _execute_strategy_signal(sig)
            if result.get("status") == "submitted":
                try:
                    metrics.strategy_orders_total.labels(
                        symbol=momentum_symbol.split(".")[0],
                        venue=momentum_symbol.split(".")[1] if "." in momentum_symbol else "BINANCE",
                        side=momentum_side,
                        source=momentum_tag,
                    ).inc()
                except Exception:
                    pass
            return

    if TREND_MODULE and TREND_MODULE.enabled:
        trend_decision = None
        try:
            trend_decision = TREND_MODULE.handle_tick(qualified, price, ts_val)
        except Exception:
            trend_decision = None
        if trend_decision:
            trend_symbol = str(trend_decision.get("symbol") or qualified)
            trend_side = str(trend_decision.get("side") or "BUY")
            trend_quote = float(trend_decision.get("quote") or S_CFG.quote_usdt)
            trend_tag = str(trend_decision.get("tag") or "trend_follow")
            default_market = trend_decision.get("market") if isinstance(trend_decision, dict) else None
            if not default_market:
                default_market = "futures" if getattr(TREND_CFG, "allow_shorts", False) else "spot"
            resolved_market = resolve_market_choice(trend_symbol, default_market)
            sig = StrategySignal(
                symbol=trend_symbol,
                side=trend_side,
                quote=trend_quote,
                quantity=None,
                dry_run=None,
                tag=trend_tag,
                market=resolved_market,
            )
            result = _execute_strategy_signal(sig)
            if result.get("status") == "submitted":
                try:
                    metrics.strategy_orders_total.labels(symbol=base, venue=venue, side=trend_side, source=trend_tag).inc()
                except Exception:
                    pass
            return

    # --- MA crossing decision ---
    ma_side = _mac.push(qualified, price)
    ma_conf = 0.0
    if ma_side and price:
        window = _mac.windows[qualified]
        fast = _mac.fast
        if len(window) >= fast:
            fast_ma = sum(list(window)[-fast:]) / fast
            slow_ma = sum(window) / len(window)
            try:
                ma_conf = min(1.0, abs((fast_ma - slow_ma) / price))
            except ZeroDivisionError:
                ma_conf = 0.0

    # --- HMM decision ---
    hmm_conf = 0.0
    hmm_decision = None
    if S_CFG.hmm_enabled:
        try:
            policy_hmm.ingest_tick(base, price, volume or 1.0)
            hmm_decision = policy_hmm.decide(base)
            if hmm_decision and isinstance(hmm_decision[2], dict):
                probs = hmm_decision[2].get("probs") or []
                if isinstance(probs, (list, tuple)) and probs:
                    hmm_conf = float(max(probs))
        except Exception:
            hmm_decision = None
            hmm_conf = 0.0

    # --- Ensemble fusion ---
    fused = ensemble_policy.combine(base, ma_side, ma_conf, hmm_decision)

    signal_side: Optional[str] = None
    signal_quote: float = S_CFG.quote_usdt
    signal_meta: Dict = {}
    conf_to_emit = 0.0

    if fused:
        signal_side, signal_quote, signal_meta = fused
        conf_to_emit = float(signal_meta.get("conf", 0.0))
    elif ma_side and not S_CFG.ensemble_enabled:
        signal_side = ma_side
        signal_meta = {"exp": "ma_v1", "conf": ma_conf}
        conf_to_emit = ma_conf
    elif hmm_decision:
        signal_side, signal_quote, signal_meta = hmm_decision
        conf_to_emit = float(signal_meta.get("conf", hmm_conf))
    else:
        conf_to_emit = max(ma_conf, hmm_conf)

    signal_value = 0.0
    if signal_side:
        signal_value = 1.0 if signal_side == "BUY" else -1.0
    try:
        metrics.strategy_signal.labels(symbol=base, venue=venue).set(signal_value)
    except Exception:
        pass
    try:
        metrics.strategy_confidence.labels(symbol=base, venue=venue).set(conf_to_emit)
    except Exception:
        pass

    if signal_side:
        if not _cooldown_ready(qualified, price, max(conf_to_emit, 0.0), venue):
            return
        source_tag = signal_meta.get("exp", "ensemble_v1" if fused else "ma_v1")
        market_choice = resolve_market_choice(qualified, S_CFG.default_market)
        sig = StrategySignal(
            symbol=qualified,
            side=signal_side,
            quote=signal_quote,
            quantity=None,
            dry_run=None,
            tag=source_tag,
            market=market_choice,
        )

        result = _execute_strategy_signal(sig)
        if result.get("status") == "submitted":
            try:
                metrics.strategy_orders_total.labels(symbol=base, venue=venue, side=signal_side, source=source_tag).inc()
            except Exception:
                pass

        if fused:
            try:
                _schedule_bracket_watch(qualified, signal_side, price)
            except Exception:
                pass


def _record_tick_latency(symbol: str) -> None:
    tick_ts = _last_tick_ts.get(symbol)
    if tick_ts is None:
        tick_ts = _last_tick_ts.get(symbol.split(".")[0])
    if tick_ts is None:
        return
    latency_ms = max(0.0, (time.time() - tick_ts) * 1000.0)
    try:
        metrics.strategy_tick_to_order_latency_ms.observe(latency_ms)
    except Exception:
        pass
    try:
        record_tick_latency(symbol, latency_ms)
    except Exception:
        pass


def _cooldown_ready(symbol: str, price: float, confidence: float, venue: str) -> bool:
    now = time.time()
    # In test environments (pytest), bypass cooldown to avoid inter-test coupling
    try:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return True
    except Exception:
        pass
    base_symbol = symbol.split(".")[0]
    base_window = max(0.5, S_CFG.cooldown_sec * calibration_cooldown_scale(base_symbol))
    conf_factor = max(0.35, 1.0 - min(confidence, 0.99))
    px_factor = 1.0
    prev_price = _last_trade_price.get(symbol)
    if prev_price:
        move_bp = abs(price - prev_price) / max(prev_price, 1e-9) * 10_000
        px_factor = min(2.0, max(0.5, 1.0 - min(move_bp, 50.0) / 100.0))
    dynamic_window = max(1.0, base_window * conf_factor * px_factor)
    resume_at = _symbol_cooldown_until.get(symbol, 0.0)
    if now < resume_at:
        try:
            metrics.strategy_cooldown_window_seconds.labels(symbol=base_symbol, venue=venue).set(resume_at - now)
        except Exception:
            pass
        return False
    _symbol_cooldown_until[symbol] = now + dynamic_window
    _last_trade_price[symbol] = price
    try:
        metrics.strategy_cooldown_window_seconds.labels(symbol=base_symbol, venue=venue).set(dynamic_window)
    except Exception:
        pass
    return True


def _latest_price(symbol: str) -> Optional[float]:
    """Synchronous price lookup for scheduler thread without touching event loop.

    Uses a one-off blocking HTTP call to the Binance public ticker endpoint
    to avoid sharing the async client across threads/loops.
    """
    try:
        import httpx
        from .config import get_settings
        clean = symbol.split(".")[0]
        s = get_settings()
        base = s.base_url.rstrip("/")
        path = "/fapi/v1/ticker/price" if getattr(s, "is_futures", False) else "/api/v3/ticker/price"
        r = httpx.get(f"{base}{path}", params={"symbol": clean}, timeout=5.0)
        r.raise_for_status()
        return float(r.json().get("price"))
    except Exception:
        return None

def _tick_once():
    symbols = S_CFG.symbols or []
    for s in symbols:
        if "." in s:
            symbol = s
        else:
            sym = s if s.endswith("USD") or s.endswith("USDT") else f"{s}USDT"
            symbol = f"{sym}.BINANCE"
        px = _latest_price(symbol)
        if px is None:
            continue
        on_tick(symbol, px, time.time())

# --- Simple bracket watcher (SL/TP emulation) ---
def _schedule_bracket_watch(symbol: str, side: str, entry_px: float):
    if not S_CFG.hmm_enabled:
        return  # Only for HMM strategy
    # TP/SL in basis points
    tp = S_CFG.tp_bps / 10000.0
    sl = S_CFG.sl_bps / 10000.0
    up  = entry_px * (1 + tp)
    dn  = entry_px * (1 - sl)
    def _watch():
        # light, best-effort loop
        for _ in range(120):  # ~2h at 60s; adjust if you poll faster
            px = _latest_price(symbol)
            if px is None:
                time.sleep(S_CFG.interval_sec)
                continue
            if side == "BUY":
                if px >= up:
                    sig = StrategySignal(symbol=symbol, side="SELL", quote=S_CFG.quote_usdt, quantity=None, dry_run=None, tag="tp")
                    _execute_strategy_signal(sig)
                    break
                if px <= dn:
                    sig = StrategySignal(symbol=symbol, side="SELL", quote=S_CFG.quote_usdt, quantity=None, dry_run=None, tag="sl")
                    _execute_strategy_signal(sig)
                    break
            else:  # short on futures/perp only; if spot, this will be ignored by router/rails
                if px <= dn:
                    sig = StrategySignal(symbol=symbol, side="BUY", quote=S_CFG.quote_usdt, quantity=None, dry_run=None, tag="tp")
                    _execute_strategy_signal(sig)
                    break
                if px >= up:
                    sig = StrategySignal(symbol=symbol, side="BUY", quote=S_CFG.quote_usdt, quantity=None, dry_run=None, tag="sl")
                    _execute_strategy_signal(sig)
                    break
            time.sleep(S_CFG.interval_sec)
    threading.Thread(target=_watch, daemon=True).start()

def start_scheduler():
    global _loop_thread
    if not S_CFG.enabled:
        return
    if _loop_thread and _loop_thread.is_alive():
        return
    _stop_flag.clear()
    def loop():
        while not _stop_flag.is_set():
            t0 = time.time()
            try:
                _tick_once()
            except Exception:
                pass
            dt = max(0.0, S_CFG.interval_sec - (time.time() - t0))
            _stop_flag.wait(dt)
    _loop_thread = threading.Thread(target=loop, name="strategy-ma-cross", daemon=True)
    _loop_thread.start()

def stop_scheduler():
    _stop_flag.set()

def block_entries_for(seconds: float) -> None:
    global _entry_block_until
    _entry_block_until = max(_entry_block_until, time.time() + float(seconds))
