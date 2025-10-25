from __future__ import annotations
import asyncio, inspect, os
import threading, time, uuid
from collections import deque, defaultdict
from typing import Callable, Deque, Dict, List, Optional, cast
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .config import load_strategy_config, load_risk_config
from .risk import RiskRails, Side
from .idempotency import CACHE, append_jsonl
from . import metrics
from .core import order_router
from .strategies import policy_hmm, ensemble_policy
from .strategies.calibration import cooldown_scale as calibration_cooldown_scale

router = APIRouter()
S_CFG = load_strategy_config()
R_CFG = load_risk_config()
RAILS = RiskRails(R_CFG)

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

class StrategySignal(BaseModel):
    symbol: str = Field(..., description="e.g. BTCUSDT.BINANCE")
    side: str = Field(..., pattern=r"^(BUY|SELL)$")
    quote: Optional[float] = Field(None, description="USDT notional (preferred)")
    quantity: Optional[float] = Field(None, description="Base qty (alternative)")
    dry_run: Optional[bool] = Field(None, description="Override STRATEGY_DRY_RUN")
    tag: Optional[str] = Field(None, description="Optional label (e.g. 'ma_cross')")

@router.post("/strategy/signal")
def post_strategy_signal(sig: StrategySignal, request: Request):
    idem = request.headers.get("X-Idempotency-Key")
    return _execute_strategy_signal(sig, idem_key=idem)


def _execute_strategy_signal(sig: StrategySignal, *, idem_key: Optional[str] = None) -> Dict:
    side_literal = cast(Side, sig.side)
    ok, err = RAILS.check_order(symbol=sig.symbol, side=side_literal, quote=sig.quote, quantity=sig.quantity)
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

    if sig.quantity is not None:
        res = order_router_instance.market_quantity(sig.symbol, side_literal, sig.quantity)
    else:
        res = order_router_instance.market_quote(sig.symbol, side_literal, sig.quote or 0.0)

    _record_tick_latency(sig.symbol)

    metrics.orders_submitted.inc()
    resp = {
        "status": "submitted",
        "order": res,
        "tag": sig.tag or "strategy",
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
        sig = StrategySignal(
            symbol=qualified,
            side=signal_side,
            quote=signal_quote,
            quantity=None,
            dry_run=None,
            tag=source_tag,
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
