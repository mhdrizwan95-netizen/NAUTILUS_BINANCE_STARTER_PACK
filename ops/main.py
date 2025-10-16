from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque, defaultdict
from typing import Deque, Dict, List, Optional, Tuple

import httpx
# Slippage model (keep import near top)
from ops.slip_model import (
    load_model as load_slip_model,
    predict_slip_bp,
    append_row_to_parquet,
)

# Adaptive allocator
from ops.allocator import Allocator, TOTAL_ALLOC_USD, ALLOC_ALPHA, ALLOC_BETA, ALLOC_SMOOTH


# ------------------------- Config helpers ------------------------------------

def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _as_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "y", "on"}


ENGINE_URL = os.getenv("ENGINE_URL", "http://engine_binance:8003").rstrip("/")
ENABLE_EXECUTION = _as_bool("ENABLE_EXECUTION", True)

# File produced by vol_ranker; checked dynamically
VOL_TOP_FILE = os.getenv("VOL_TOP_FILE", "data/top_symbols.txt")
DEFAULT_SYMBOLS = os.getenv("SYMBOLS")
# Dynamic sizing knobs
BASE_SIZE_USD = _as_float("BASE_SIZE_USD", 30.0)
ATRP_REF = _as_float("ATRP_REF", 0.004)  # 0.4%/min
BETA_CONF = _as_float("BETA_CONF", 1.0)
EXPO_CAP_SYM = _as_float("EXPOSURE_CAP_SYMBOL_USD", 300.0)
EXPO_CAP_TOT = _as_float("EXPOSURE_CAP_TOTAL_USD", 1500.0)
VOL_N = _as_int("VOL_LOOKBACK_MIN", 30)
SLIP_LIMIT_THRESH_BP = _as_float("SLIP_LIMIT_THRESH_BP", 12.0)
SLIP_MARKET_THRESH_BP = _as_float("SLIP_MARKET_THRESH_BP", 40.0)
LIMIT_ADD_BP = _as_float("LIMIT_ADD_BP", 4.0)
MAX_SLIP_BP_HARD = _as_float("MAX_SLIP_BP_HARD", 120.0)
IOC_MARKET_BACKOFF_SEC = _as_int("IOC_MARKET_BACKOFF_SEC", 300)
# Autonomous exit knobs
ENABLE_SELLS = _as_bool("ENABLE_SELLS", True)
HOLD_SEC = _as_int("HOLD_SEC", 240)
TP_BP = _as_float("TP_BP", 0.0)
SL_BP = _as_float("SL_BP", 0.0)
PROBE_USDT = _as_float("PROBE_USDT", 30.0)
MAX_SLIP_BP = _as_float("MAX_SLIP_BP", 120.0)
MAX_ORDERS_PER_MIN = _as_int("MAX_ORDERS_PER_MIN", 20)
MAX_PARALLEL_ORDERS = _as_int("MAX_PARALLEL_ORDERS", 3)
PROBE_COOLDOWN_SEC = _as_int("PROBE_COOLDOWN_SEC", 90)
SSE_URL = os.getenv("ENGINE_SSE_URL", f"{ENGINE_URL}/stream")

# Prometheus metrics server for executor
try:
    from prometheus_client import Gauge, start_http_server
    from prometheus_client import Counter, Histogram

    EXEC_METRICS_PORT = _as_int("EXEC_METRICS_PORT", 9102)
    DYN_SIZE_G = Gauge("dynamic_size_usd", "Executor dynamic quote size (USD)", ["symbol"])  # noqa: N816
    ATR_PCT_G = Gauge("atr_percent", "ATR percent (1m)", ["symbol"])  # noqa: N816
    CONF_G = Gauge("confidence", "Model confidence (0..1)", ["symbol"])  # noqa: N816
    # Extra metrics for slippage modeling
    PRED_SLIP_G = Gauge("predicted_slippage_bp", "Predicted slippage (bps)", ["symbol"])  # noqa: N816
    EXEC_TACTIC_C = Counter("execution_tactic_total", "Execution tactic used", ["symbol", "tactic"])  # noqa: N816
    SLIP_OBS_H = Histogram(
        "slip_observed_bp",
        "Observed slippage (bps)",
        ["symbol"],
        buckets=[1, 2, 5, 10, 20, 40, 80, 120, 200],
    )
    # Start a background HTTP server to expose /metrics
    start_http_server(EXEC_METRICS_PORT)
except Exception:
    DYN_SIZE_G = None
    ATR_PCT_G = None
    CONF_G = None
    PRED_SLIP_G = None
    EXEC_TACTIC_C = None
    SLIP_OBS_H = None


# ------------------------- Rate control --------------------------------------

class RateLimiter:
    def __init__(self, max_per_min: int) -> None:
        self.max_per_min = max_per_min
        self.events: Deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        cutoff = now - 60.0
        while self.events and self.events[0] < cutoff:
            self.events.popleft()
        if len(self.events) >= self.max_per_min:
            return False
        self.events.append(now)
        return True


# ------------------------- Engine helpers ------------------------------------

async def get_universe() -> List[str]:
    # 1) Prefer dynamic file written by vol_ranker
    try:
        if os.path.exists(VOL_TOP_FILE):
            with open(VOL_TOP_FILE) as f:
                lines = [ln.strip() for ln in f if ln.strip()]
                if lines:
                    return lines
    except Exception:
        pass
    # 2) Fallback to explicit env
    if DEFAULT_SYMBOLS:
        return [s.strip() for s in DEFAULT_SYMBOLS.split(",") if s.strip()]
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{ENGINE_URL}/universe")
            r.raise_for_status()
            data = r.json()
            syms = data.get("symbols") or []
            return [s.split(".")[0] for s in syms if s.split(".")[0].endswith("USDT")]
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


# ------------------------- Dynamic sizing helpers ----------------------------

_ATR_CACHE: Dict[str, Tuple[float, float]] = {}
_CONF_CACHE: Dict[str, Tuple[float, float]] = {}
_EXPO_CACHE: Tuple[float, Dict[str, float], float] | None = None  # total, per-sym, ts
_POS_CACHE: Tuple[Dict[str, float], float] | None = None  # qty_base by symbol, ts
_KLINE_CACHE: Dict[str, Tuple[float, List[Tuple[float, float, float, float]]]] = {}
_IOC_FAILS: Dict[str, int] = {}
_IOC_BACKOFF_UNTIL: Dict[str, float] = {}
_SLIP_MODEL = load_slip_model()

# Track local lots for autonomous exits
open_positions: Dict[str, Dict[str, float]] = {}


async def fetch_klines_1m(symbol: str, limit: int = 60) -> List[Tuple[float, float, float, float]]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit={limit}"
    try:
        now = time.time()
        ts, cached = _KLINE_CACHE.get((symbol, limit), (0.0, [])) if False else (0.0, [])
        # simple cache key per symbol regardless of limit
        ts2, cached2 = _KLINE_CACHE.get(symbol, (0.0, []))
        if (now - ts2) < 10.0 and cached2:
            return cached2[-limit:]
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            arr = [(float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in data]
            _KLINE_CACHE[symbol] = (now, arr)
            return arr
    except Exception:
        return []


async def atr_percent_1m(symbol: str, n: int = 30) -> float:
    now = time.time()
    ts, val = _ATR_CACHE.get(symbol, (0.0, 0.0))
    if (now - ts) < 60.0 and val > 0.0:
        return val
    ks = await fetch_klines_1m(symbol, limit=max(n + 1, 35))
    if len(ks) < n + 1:
        return 0.0
    tr: List[float] = []
    prev_close = ks[0][3]
    for (_o, h, l, c) in ks[1:]:
        tr.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
        prev_close = c
    atr = sum(tr[-n:]) / float(n)
    last_close = ks[-1][3]
    atrp = (atr / last_close) if last_close else 0.0
    _ATR_CACHE[symbol] = (now, atrp)
    return atrp


async def get_confidence(symbol: str) -> float:
    now = time.time()
    ts, val = _CONF_CACHE.get(symbol, (0.0, 0.5))
    if (now - ts) < 60.0:
        return val
    # Placeholder: try to fetch from a policy service if available
    conf = 0.5
    # Example (disabled):
    # try:
    #     async with httpx.AsyncClient(timeout=0.5) as client:
    #         r = await client.get(f"http://ml_service:8010/conf?symbol={symbol}")
    #         if r.status_code == 200:
    #             conf = float(r.json().get("confidence", 0.5))
    # except Exception:
    #     pass
    conf = max(0.0, min(1.0, conf))
    _CONF_CACHE[symbol] = (now, conf)
    return conf


async def current_exposures() -> Tuple[float, Dict[str, float]]:
    global _EXPO_CACHE
    now = time.time()
    if _EXPO_CACHE and (now - _EXPO_CACHE[2]) < 5.0:
        return _EXPO_CACHE[0], _EXPO_CACHE[1]
    total = 0.0
    per: Dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{ENGINE_URL}/portfolio")
            r.raise_for_status()
            snap = r.json()
            positions = snap.get("positions", [])
            for p in positions:
                sym = (p.get("symbol") or "").split(".")[0]
                qty = float(p.get("qty_base") or 0.0)
                last = p.get("last_price_quote")
                val = float(p.get("value_usd") or 0.0)
                if val == 0.0 and last is not None:
                    val = abs(qty * float(last))
                val = abs(val)
                total += val
                per[sym] = per.get(sym, 0.0) + val
    except Exception:
        pass
    _EXPO_CACHE = (total, per, now)
    return total, per


async def current_positions_qty() -> Dict[str, float]:
    global _POS_CACHE
    now = time.time()
    if _POS_CACHE and (now - _POS_CACHE[1]) < 5.0:
        return _POS_CACHE[0]
    qtys: Dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{ENGINE_URL}/portfolio")
            r.raise_for_status()
            snap = r.json()
            for p in snap.get("positions", []):
                sym = (p.get("symbol") or "").split(".")[0]
                qty = float(p.get("qty_base") or 0.0)
                qtys[sym] = qty
    except Exception:
        pass
    _POS_CACHE = (qtys, now)
    return qtys


async def dynamic_quote_size(symbol: str, min_notional: float) -> Tuple[float, float, float, float]:
    conf = await get_confidence(symbol)
    atrp = await atr_percent_1m(symbol, VOL_N)
    if atrp <= 0.0:
        atrp = ATRP_REF
    vol_scale = max(0.5, min(2.0, atrp / ATRP_REF))
    quote = BASE_SIZE_USD * (1.0 + BETA_CONF * (conf - 0.5)) * vol_scale
    quote = max(quote, 1.1 * float(min_notional))
    # Per-order hard ceiling at symbol cap
    quote = min(quote, EXPO_CAP_SYM)
    return float(quote), float(atrp), float(conf), float(vol_scale)


async def get_l1(symbol: str) -> Tuple[float, float, float, float, float]:
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": symbol, "limit": 5}
    try:
        async with httpx.AsyncClient(timeout=0.8) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            j = r.json()
            bid = float(j["bids"][0][0]); bid_q = float(j["bids"][0][1])
            ask = float(j["asks"][0][0]); ask_q = float(j["asks"][0][1])
            mid = 0.5 * (bid + ask)
            return bid, ask, bid_q, ask_q, mid
    except Exception:
        return 0.0, 0.0, 0.0, 0.0, 0.0


async def vol_accel_5m_over_30m(symbol: str) -> float:
    ks = await fetch_klines_1m(symbol, limit=35)
    if len(ks) < 6:
        return 1.0
    closes = [k[3] for k in ks]
    rets = []
    prev = closes[0]
    for c in closes[1:]:
        rets.append((c - prev) / prev if prev else 0.0)
        prev = c
    if len(rets) < 30:
        return 1.0
    import statistics
    sd5 = statistics.pstdev(rets[-5:]) if len(rets) >= 5 else 0.0
    sd30 = statistics.pstdev(rets[-30:]) if len(rets) >= 30 else 1e-9
    if sd30 <= 0:
        sd30 = 1e-9
    return float(sd5 / sd30)


def _expected_slip_bp(symbol: str, side: str, features: Dict[str, float]) -> float:
    try:
        if _SLIP_MODEL is None:
            sbp = features.get("spread_bp", 0.0)
            size_ratio = min(3.0, max(0.1, features.get("order_quote_usd", 0.0) / (features.get("depth_usd", 0.0) + 1e-6)))
            return 0.5 * sbp * size_ratio
        return predict_slip_bp(_SLIP_MODEL, features)
    except Exception:
        return features.get("spread_bp", 0.0)


async def symbol_info(symbol: str) -> dict:
    async with httpx.AsyncClient(timeout=6.0) as client:
        r = await client.get(f"{ENGINE_URL}/symbol_info", params={"symbol": symbol})
        r.raise_for_status()
        return r.json()


async def last_prices() -> dict:
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{ENGINE_URL}/prices")
            r.raise_for_status()
            return r.json().get("prices", {})
    except Exception:
        return {}


async def submit_market_quote(symbol: str, side: str, quote: float, idem: str) -> dict:
    payload = {"symbol": symbol, "side": side, "quote": float(quote)}
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.post(
            f"{ENGINE_URL}/orders/market",
            headers={"Content-Type": "application/json", "X-Idempotency-Key": idem},
            json=payload,
        )
        r.raise_for_status()
        return r.json()


async def submit_limit_ioc(symbol: str, side: str, quote: float, price: float, idem: str) -> dict:
    payload = {
        "symbol": symbol,
        "side": side,
        "quote": float(quote),
        "price": float(price),
        "timeInForce": "IOC",
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.post(
            f"{ENGINE_URL}/orders/limit",
            headers={"Content-Type": "application/json", "X-Idempotency-Key": idem},
            json=payload,
        )
        r.raise_for_status()
        return r.json()


# ------------------------- SSE listener (optional) ---------------------------

async def sse_listener(url: str) -> None:
    """Keep an SSE connection open for future reactive strategies.

    This executor does not act on events yet; the stream is used as liveness.
    """
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as resp:
                    async for line in resp.aiter_lines():
                        # No-op; could parse event/data if needed
                        if not line:
                            await asyncio.sleep(0)
        except Exception:
            await asyncio.sleep(2.0)


# ------------------------- Probing loop --------------------------------------

async def probe_loop() -> None:
    symbols = await get_universe()
    # Symbol refresh cadence (seconds); default 1 hour
    SYMBOL_REFRESH_SEC = _as_int("SYMBOL_REFRESH_SEC", 3600)
    last_refresh = time.time()
    prices = await last_prices()
    last_ts: Dict[str, float] = defaultdict(lambda: 0.0)
    limiter = RateLimiter(MAX_ORDERS_PER_MIN)
    sem = asyncio.Semaphore(MAX_PARALLEL_ORDERS)

    # Initialize adaptive allocator
    alloc = Allocator(total_usd=TOTAL_ALLOC_USD, alpha=ALLOC_ALPHA, beta=ALLOC_BETA, smooth=ALLOC_SMOOTH)

    async def probe_one(sym: str) -> None:
        now = time.time()
        if (now - last_ts[sym]) < PROBE_COOLDOWN_SEC:
            return
        info = await symbol_info(sym)
        min_notional = float(info.get("min_notional", 5.0))
        # Dynamic sizing
        quote, atrp, conf, vol_scale = await dynamic_quote_size(sym, min_notional)
        side = "BUY"
        # Only flip to SELL when exit policy permits (HOLD/TP/SL)
        try:
            if ENABLE_SELLS:
                pos_qty = (await current_positions_qty()).get(sym, 0.0)
                px_for_pos = float(prices.get(sym)) if sym in prices else 0.0
                pos_val = abs(pos_qty * px_for_pos) if (pos_qty and px_for_pos) else 0.0
                if pos_qty > 0.0 and pos_val > 1.1 * min_notional:
                    exit_ok = False
                    # If we tracked an entry, respect hold/tp/sl thresholds
                    if sym in open_positions:
                        age = now - float(open_positions[sym].get("ts", now))
                        entry_px = float(open_positions[sym].get("price") or 0.0)
                        pnl_bp = ((px_for_pos - entry_px) / entry_px * 10_000.0) if entry_px > 0 else 0.0
                        if TP_BP > 0 and pnl_bp >= TP_BP:
                            exit_ok = True
                        elif SL_BP > 0 and pnl_bp <= -SL_BP:
                            exit_ok = True
                        elif HOLD_SEC > 0 and age >= HOLD_SEC:
                            exit_ok = True
                    # If we don't have a tracked entry, avoid opportunistic sells
                    if exit_ok:
                        side = "SELL"
                        quote = min(quote, pos_val)
        except Exception:
            pass

        # Apply allocator scaling based on tactic performance
        # Tactic determination is done after L1 fetch below
        # Exposure pre-checks
        try:
            tot, per = await current_exposures()
            if side == "BUY" and (tot + quote) > EXPO_CAP_TOT:
                last_ts[sym] = now
                return
            if side == "BUY" and (per.get(sym, 0.0) + quote) > EXPO_CAP_SYM:
                last_ts[sym] = now
                return
        except Exception:
            pass
        # Update gauges (best-effort)
        try:
            if DYN_SIZE_G is not None:
                DYN_SIZE_G.labels(sym).set(quote)
            if ATR_PCT_G is not None:
                ATR_PCT_G.labels(sym).set(atrp)
            if CONF_G is not None:
                CONF_G.labels(sym).set(conf)
        except Exception:
            pass
        if not limiter.allow():
            return
        async with sem:
            last = None
            try:
                last = float(prices.get(sym)) if sym in prices else None
            except Exception:
                last = None
            idem = f"exec:{sym}:{int(now)}:{side}"
            try:
                if not ENABLE_EXECUTION:
                    last_ts[sym] = now
                    return
                # Pre-trade L1 snapshot
                bid, ask, bid_q, ask_q, mid = await get_l1(sym)
                spread_bp = ((ask - bid) / mid * 10_000.0) if (bid and ask and mid) else 0.0
                depth_usd = min(bid * bid_q, ask * ask_q) if (bid and ask and bid_q and ask_q) else 0.0
                accel = await vol_accel_5m_over_30m(sym)
                feats = {
                    "spread_bp": spread_bp,
                    "depth_imbalance": ((bid_q - ask_q) / (bid_q + ask_q + 1e-9)) if (bid_q or ask_q) else 0.0,
                    "depth_usd": depth_usd,
                    "atrp_1m": atrp,
                    "order_quote_usd": (quote / (depth_usd + 1e-9)) if depth_usd > 0 else 0.0,
                    "is_burst": 1.0 if accel > 1.2 else 0.0,
                    "side": 1.0 if side == "BUY" else -1.0,
                }
                slip_pred = _expected_slip_bp(sym, side, feats)
                # Metrics
                try:
                    if PRED_SLIP_G is not None:
                        PRED_SLIP_G.labels(sym).set(slip_pred)
                except Exception:
                    pass

                # Decide tactic
                tactic = "MARKET"
                res = None
                # Backoff: if too many IOC non-fills recently, force MARKET
                if _IOC_BACKOFF_UNTIL.get(sym, 0.0) > now:
                    slip_pred = max(slip_pred, SLIP_MARKET_THRESH_BP + 1.0)  # force market branch below

                if slip_pred <= SLIP_LIMIT_THRESH_BP and bid and ask:
                    # LIMIT IOC with hard slip cap relative to mid
                    if mid <= 0:
                        if side == "BUY":
                            limit_px = ask * (1 + LIMIT_ADD_BP / 10_000.0)
                        else:
                            limit_px = bid * (1 - LIMIT_ADD_BP / 10_000.0)
                    else:
                        if side == "BUY":
                            cap_px = mid * (1 + MAX_SLIP_BP_HARD / 10_000.0)
                            limit_px = min(ask * (1 + LIMIT_ADD_BP / 10_000.0), cap_px)
                        else:
                            cap_px = mid * (1 - MAX_SLIP_BP_HARD / 10_000.0)
                            limit_px = max(bid * (1 - LIMIT_ADD_BP / 10_000.0), cap_px)
                    # Apply allocator scaling to quote size
                    quote = alloc.get_tactic_allocation("LIMIT_IOC", quote)
                    res = await submit_limit_ioc(sym, side, quote, limit_px, idem)
                    tactic = "LIMIT_IOC"
                elif slip_pred <= SLIP_MARKET_THRESH_BP:
                    # Apply allocator scaling to quote size
                    quote = alloc.get_tactic_allocation("MARKET_MOD", quote)
                    res = await submit_market_quote(sym, side, quote, idem)
                    tactic = "MARKET_MOD"
                else:
                    # Skip due to high predicted slippage
                    last_ts[sym] = now
                    try:
                        if EXEC_TACTIC_C is not None:
                            EXEC_TACTIC_C.labels(sym, "SKIP").inc()
                    except Exception:
                        pass
                    return

                order = res.get("order", {})
                status = order.get("status") or res.get("status")
                avg_px = float(order.get("avg_fill_price") or 0.0)
                if last and avg_px:
                    slip_bps = abs(avg_px - last) / last * 10_000.0
                    if slip_bps > MAX_SLIP_BP:
                        # Optional: could submit immediate SELL to unwind
                        pass
                last_ts[sym] = now
                # Observed slippage vs mid at submit
                try:
                    if avg_px > 0 and mid > 0:
                        side_sign = 1.0 if side == "BUY" else -1.0
                        slip_obs_bp = side_sign * ((avg_px - mid) / mid * 10_000.0)
                        if SLIP_OBS_H is not None:
                            SLIP_OBS_H.labels(sym).observe(max(0.0, slip_obs_bp))
                        # IOC non-fill tracking (treat zero fill)
                        filled_qty = float(order.get("filled_qty_base") or 0.0)
                        if tactic == "LIMIT_IOC" and filled_qty <= 0:
                            _IOC_FAILS[sym] = _IOC_FAILS.get(sym, 0) + 1
                            if _IOC_FAILS[sym] >= 3:
                                _IOC_BACKOFF_UNTIL[sym] = now + IOC_MARKET_BACKOFF_SEC
                        else:
                            _IOC_FAILS[sym] = 0
                except Exception:
                    pass
                # Record trade metrics for allocator
                try:
                    # Calculate realized PnL, drawdown from this trade
                    pnl_usd = 0.0
                    drawdown_bp = 0.0
                    if side == "BUY":
                        # Assume position was held and this fill enters it
                        # We'll calculate simplistic metrics since true PnL needs closed position
                        pnl_usd = 0.0  # Placeholder - needs position matching logic
                        drawdown_bp = slip_obs_bp  # Use slippage as proxy
                    else:
                        # SELL exit - calculate PnL from entry
                        if sym in open_positions:
                            entry_px = float(open_positions[sym].get("price", avg_px))
                            pnl_bp = (avg_px - entry_px) / entry_px * 10_000.0 if entry_px > 0 else 0.0
                            qty_held = float(open_positions[sym].get("qty", 0.0))
                            pnl_usd = (pnl_bp / 10_000.0) * (entry_px * qty_held)
                            drawdown_bp = min(0.0, pnl_bp) if pnl_bp < 0 else 0.0  # Drawdown if loss
                        else:
                            pnl_usd = 0.0
                            drawdown_bp = 0.0

                    # Record trade in allocator for scoring
                    alloc.record_trade(tactic, pnl_usd, slip_obs_bp, drawdown_bp, now)
                except Exception:
                    pass

                # Append training row
                row = {
                    "ts": int(now),
                    "symbol": sym,
                    "side": side_sign,
                    "spread_bp": spread_bp,
                    "depth_imbalance": feats["depth_imbalance"],
                    "depth_usd": depth_usd,
                    "atrp_1m": atrp,
                    "order_quote_usd": feats["order_quote_usd"],
                    "is_burst": feats["is_burst"],
                    "mid_submit": mid,
                    "avg_fill_price": avg_px,
                    "slip_bp": slip_obs_bp,
                    "pred_bp": slip_pred,
                    "tactic": tactic,
                }
                append_row_to_parquet(row)
            except Exception as e:
                print(json.dumps({"symbol": sym, "error": str(e)}))
                # Still update counter even on exception
                try:
                    if EXEC_TACTIC_C is not None:
                        EXEC_TACTIC_C.labels(sym, tactic if 'tactic' in locals() else "UNKNOWN").inc()
                except Exception:
                    pass

                # Track opened/closed positions for autonomous exits
                try:
                    filled_qty = float(order.get("filled_qty_base") or 0.0)
                    if filled_qty > 0 and ENABLE_SELLS:
                        if side == "BUY":
                            open_positions[sym] = {"price": avg_px, "qty": filled_qty, "ts": now}
                        else:
                            if sym in open_positions:
                                del open_positions[sym]
                except Exception:
                    pass

                print(
                    json.dumps(
                        {
                            "symbol": sym,
                            "status": status,
                            "avg_px": avg_px,
                            "side": side,
                            "quote_usd": quote,
                            "atr_percent": atrp,
                            "conf": conf,
                            "vol_scale": vol_scale,
                            "pred_slip_bp": slip_pred,
                            "tactic": tactic,
                        }
                    )
                )

    # Round-robin forever; symbols refreshed periodically
    i = 0
    while True:
        # Periodically refresh prices
        if i % max(1, len(symbols)) == 0:
            prices = await last_prices()
        # Autonomous exit checks (TP/SL/HOLD)
        if ENABLE_SELLS and open_positions:
            now_ts = time.time()
            # Seed tracker for any live positions not yet tracked (enables HOLD exit for manual entries)
            try:
                live_qtys = await current_positions_qty()
                for sym_l, qty_l in live_qtys.items():
                    if qty_l > 0 and sym_l not in open_positions:
                        px_l = None
                        try:
                            px_l = float(prices.get(sym_l)) if sym_l in prices else None
                        except Exception:
                            px_l = None
                        if px_l and px_l > 0:
                            open_positions[sym_l] = {"price": px_l, "qty": float(qty_l), "ts": now_ts}
            except Exception:
                pass

            for sym, pos in list(open_positions.items()):
                try:
                    age = now_ts - float(pos.get("ts", now_ts))
                    if HOLD_SEC > 0 and age < HOLD_SEC and TP_BP <= 0 and SL_BP <= 0:
                        continue
                    last_px = None
                    try:
                        last_px = float(prices.get(sym)) if sym in prices else None
                    except Exception:
                        last_px = None
                    if not last_px or last_px <= 0:
                        continue
                    entry_px = float(pos.get("price") or 0.0)
                    qty = float(pos.get("qty") or 0.0)
                    if entry_px <= 0 or qty <= 0:
                        del open_positions[sym]
                        continue
                    pnl_bp = (last_px - entry_px) / entry_px * 10_000.0
                    should_exit = False
                    if TP_BP > 0 and pnl_bp >= TP_BP:
                        should_exit = True
                    elif SL_BP > 0 and pnl_bp <= -SL_BP:
                        should_exit = True
                    elif HOLD_SEC > 0 and age >= HOLD_SEC:
                        should_exit = True
                    if should_exit:
                        # Decide tactic for SELL exit
                        bid, ask, bid_q, ask_q, mid = await get_l1(sym)
                        atrp = await atr_percent_1m(sym, VOL_N) or ATRP_REF
                        depth_usd = min(bid * bid_q, ask * ask_q) if (bid and ask and bid_q and ask_q) else 0.0
                        feats = {
                            "spread_bp": ((ask - bid) / mid * 10_000.0) if (bid and ask and mid) else 0.0,
                            "depth_imbalance": ((bid_q - ask_q) / (bid_q + ask_q + 1e-9)) if (bid_q or ask_q) else 0.0,
                            "depth_usd": depth_usd,
                            "atrp_1m": atrp,
                            "order_quote_usd": (qty * last_px) / (depth_usd + 1e-9) if depth_usd > 0 else 0.0,
                            "is_burst": 0.0,
                            "side": -1.0,
                        }
                        slip_pred = _expected_slip_bp(sym, "SELL", feats)
                        idem = f"exit:{sym}:{int(now_ts)}"
                        quote_val = qty * last_px
                        res = None
                        if slip_pred <= SLIP_LIMIT_THRESH_BP and bid and ask:
                            if mid and mid > 0:
                                cap_px = mid * (1 - MAX_SLIP_BP_HARD / 10_000.0)
                                limit_px = max(bid * (1 - LIMIT_ADD_BP / 10_000.0), cap_px)
                            else:
                                limit_px = bid * (1 - LIMIT_ADD_BP / 10_000.0)
                            res = await submit_limit_ioc(sym, "SELL", quote_val, limit_px, idem)
                        elif slip_pred <= SLIP_MARKET_THRESH_BP:
                            res = await submit_market_quote(sym, "SELL", quote_val, idem)
                        if res:
                            try:
                                del open_positions[sym]
                            except Exception:
                                pass
                except Exception:
                    pass
                except Exception:
                    pass

        # Periodically refresh symbol list from file/env/engine
        try:
            if (time.time() - last_refresh) >= max(10, SYMBOL_REFRESH_SEC):
                try:
                    new_syms = await get_universe()
                    if new_syms:
                        symbols = new_syms
                except Exception:
                    pass
                finally:
                    last_refresh = time.time()

            sym = symbols[i % len(symbols)]
            await probe_one(sym)
            i += 1
            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"executor loop error: {e}")
            await asyncio.sleep(1.0)
        sym = symbols[i % len(symbols)]
        await probe_one(sym)
        i += 1
        await asyncio.sleep(1.0)



async def main() -> None:
    print(
        json.dumps(
            {
                "engine": ENGINE_URL,
                "enable_execution": ENABLE_EXECUTION,
                "probe_usdt": PROBE_USDT,
                "base_size_usd": BASE_SIZE_USD,
                "atrp_ref": ATRP_REF,
                "beta_conf": BETA_CONF,
                "expo_cap_symbol": EXPO_CAP_SYM,
                "expo_cap_total": EXPO_CAP_TOT,
                "vol_lookback_min": VOL_N,
                "slip_limit_thresh_bp": SLIP_LIMIT_THRESH_BP,
                "slip_market_thresh_bp": SLIP_MARKET_THRESH_BP,
                "limit_add_bp": LIMIT_ADD_BP,
                "max_slip_bp_hard": MAX_SLIP_BP_HARD,
                "enable_sells": ENABLE_SELLS,
                "hold_sec": HOLD_SEC,
                "tp_bp": TP_BP,
                "sl_bp": SL_BP,
                "max_orders_per_min": MAX_ORDERS_PER_MIN,
                "max_parallel": MAX_PARALLEL_ORDERS,
                "cooldown_sec": PROBE_COOLDOWN_SEC,
            }
        )
    )
    await asyncio.gather(sse_listener(SSE_URL), probe_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
