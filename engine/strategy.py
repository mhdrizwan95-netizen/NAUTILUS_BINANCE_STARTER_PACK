from __future__ import annotations
import threading, time, uuid
from collections import deque, defaultdict
from typing import Deque, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .config import load_strategy_config, load_risk_config
from .risk import RiskRails, Side
from .idempotency import CACHE, append_jsonl
from . import metrics
from .core import order_router
from .strategies import policy_hmm, ensemble_policy

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

class StrategySignal(BaseModel):
    symbol: str = Field(..., description="e.g. BTCUSDT.BINANCE")
    side: str = Field(..., pattern=r"^(BUY|SELL)$")
    quote: Optional[float] = Field(None, description="USDT notional (preferred)")
    quantity: Optional[float] = Field(None, description="Base qty (alternative)")
    dry_run: Optional[bool] = Field(None, description="Override STRATEGY_DRY_RUN")
    tag: Optional[str] = Field(None, description="Optional label (e.g. 'ma_cross')")

@router.post("/strategy/signal")
def post_strategy_signal(sig: StrategySignal, request: Request):
    dry = S_CFG.dry_run if sig.dry_run is None else sig.dry_run

    # Rails first (no bypass)
    ok, err = RAILS.check_order(
        symbol=sig.symbol, side=sig.side, quote=sig.quote, quantity=sig.quantity  # type: ignore
    )
    if not ok:
        metrics.orders_rejected.inc()
        return {"status": "rejected", **err, "source": "strategy"}

    # Idempotency for strategy-originated orders
    idem_key = request.headers.get("X-Idempotency-Key") or f"strategy:{sig.symbol}:{sig.side}:{int(time.time())}"
    cached = CACHE.get(idem_key)
    if cached:
        return cached

    if dry:
        # Record a simulation event, no live order
        payload = {
            "status": "simulated",
            "symbol": sig.symbol,
            "side": sig.side,
            "quote": sig.quote,
            "quantity": sig.quantity,
            "tag": sig.tag or "strategy",
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        append_jsonl("orders.jsonl", payload)
        CACHE.set(idem_key, payload)
        return payload

    # Live order via router (same path as API)
    # Import the router instance from app module
    from .app import router as order_router_instance
    res = order_router_instance.market_quantity(sig.symbol, sig.side, sig.quantity or 0.0) if sig.quantity else order_router_instance.market_quote(sig.symbol, sig.side, sig.quote or 0.0)
    metrics.orders_submitted.inc()
    resp = {
        "status": "submitted",
        "order": res,
        "tag": sig.tag or "strategy",
        "idempotency_key": idem_key,
        "timestamp": time.time(),
    }
    append_jsonl("orders.jsonl", resp)
    CACHE.set(idem_key, resp)
    # Snapshot after successful route (best-effort)
    try:
        from .state import SnapshotStore
        SnapshotStore().save(order_router_instance.portfolio_snapshot())
    except Exception:
        pass
    return resp

def _latest_price(symbol: str) -> Optional[float]:
    """Synchronous price lookup for scheduler thread without touching event loop.

    Uses a one-off blocking HTTP call to the Binance public ticker endpoint
    to avoid sharing the async client across threads/loops.
    """
    try:
        import httpx
        from .config import get_settings
        clean = symbol.split(".")[0]
        base = get_settings().base_url.rstrip("/")
        r = httpx.get(f"{base}/api/v3/ticker/price", params={"symbol": clean}, timeout=5.0)
        r.raise_for_status()
        return float(r.json().get("price"))
    except Exception:
        return None

def _tick_once():
    # Iterate configured symbols
    symbols = S_CFG.symbols or []
    for s in symbols:
        sym = s if s.endswith("USDT") else f"{s}USDT"
        venue = "BINANCE" if ".BINANCE" not in sym else sym.split(".")[1]
        symbol = f"{sym}.{venue}" if ".BINANCE" not in sym else sym
        base = sym.split(".")[0]  # e.g. BTCUSDT -> BTCUSDT
        px = _latest_price(symbol)
        if px is None:
            continue

        # --- MA crossing decision ---
        ma_side = _mac.push(symbol, px)
        ma_conf = 0.0
        if ma_side:
            # Crude confidence: normalized difference between fast/slow MAs
            fast = _mac.fast
            if len(_mac.windows[symbol]) >= fast:
                fast_ma = sum(list(_mac.windows[symbol])[-fast:]) / fast
                slow_ma = sum(_mac.windows[symbol]) / len(_mac.windows[symbol])
                ma_conf = min(1.0, abs((fast_ma - slow_ma) / px))

        # --- HMM decision ---
        hmm_decision = None
        if S_CFG.hmm_enabled:
            policy_hmm.ingest_tick(base, px, 1.0)  # volume placeholder
            hmm_decision = policy_hmm.decide(base)

        # --- Ensemble fusion ---
        fused = ensemble_policy.combine(base, ma_side, ma_conf, hmm_decision)
        if fused:
            side, quote, meta = fused
            sig = StrategySignal(symbol=symbol, side=side, quote=quote, tag=meta.get("exp"))
            # Create a mock request object for the signal handler
            class MockRequest:
                headers = {}
            resp = post_strategy_signal(sig, MockRequest())
            # Optional: bracket watcher
            try:
                _schedule_bracket_watch(symbol, side, px)
            except Exception:
                pass
        # +++ Fallback: MA signal alone if ensemble didn't trigger +++
        elif ma_side and not fused and not S_CFG.ensemble_enabled:
            sig = StrategySignal(symbol=symbol, side=ma_side, quote=S_CFG.quote_usdt, tag="ma_v1")
            class MockRequest:
                headers = {}
            post_strategy_signal(sig, MockRequest())

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
                    sig = StrategySignal(symbol=symbol, side="SELL", quote=S_CFG.quote_usdt, tag="tp")
                    class MockRequest:
                        headers = {}
                    post_strategy_signal(sig, MockRequest())
                    break
                if px <= dn:
                    sig = StrategySignal(symbol=symbol, side="SELL", quote=S_CFG.quote_usdt, tag="sl")
                    class MockRequest:
                        headers = {}
                    post_strategy_signal(sig, MockRequest())
                    break
            else:  # short on futures/perp only; if spot, this will be ignored by router/rails
                if px <= dn:
                    sig = StrategySignal(symbol=symbol, side="BUY", quote=S_CFG.quote_usdt, tag="tp")
                    class MockRequest:
                        headers = {}
                    post_strategy_signal(sig, MockRequest())
                    break
                if px >= up:
                    sig = StrategySignal(symbol=symbol, side="BUY", quote=S_CFG.quote_usdt, tag="sl")
                    class MockRequest:
                        headers = {}
                    post_strategy_signal(sig, MockRequest())
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
