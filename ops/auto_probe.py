from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
from collections import defaultdict, deque
from random import SystemRandom

import httpx

_RNG = SystemRandom()
_HTTP_ERRORS = (httpx.HTTPError, asyncio.TimeoutError)
_ENV_ERRORS = (TypeError, ValueError)

# --- Symbol feed caching infrastructure ---
_SYMBOL_CACHE: deque[str] = deque(maxlen=500)
_SYMBOL_CACHE_TTL_S = 30
_SYMBOL_CACHE_EXP = 0.0


def _normalize(sym: str) -> str:
    s = sym.upper()
    # Accept screener outputs like "BTCUSDT", "BTCUSDT.BINANCE", "BINANCE:BTCUSDT"
    if ":" in s:
        s = s.split(":")[-1]
    if s.endswith(".BINANCE"):
        s = s[:-8]
    return s


async def fetch_candidates(
    client: httpx.AsyncClient, feed_url: str, fallback: list[str], limit: int
) -> list[str]:
    global _SYMBOL_CACHE_EXP
    now = time.time()
    if now < _SYMBOL_CACHE_EXP and _SYMBOL_CACHE:  # serve warm cache
        # sample from cache
        k = min(limit, len(_SYMBOL_CACHE))
        return random.sample(list(_SYMBOL_CACHE), k) if k else fallback

    try:
        r = await client.get(feed_url, timeout=5.0)
        r.raise_for_status()
        js = r.json()
        # Accept either [{"symbol":"BTCUSDT"}, ...] or ["BTCUSDT", ...]
        raw = [j["symbol"] if isinstance(j, dict) and "symbol" in j else j for j in js]
        norm = [_normalize(x) for x in raw if isinstance(x, str)]
        unique = list(dict.fromkeys(norm))  # stable de-dupe
        # refresh cache & expiry
        _SYMBOL_CACHE.clear()
        for s in unique[: _SYMBOL_CACHE.maxlen]:
            _SYMBOL_CACHE.append(s)
        _SYMBOL_CACHE_EXP = now + _SYMBOL_CACHE_TTL_S

        k = min(limit, len(unique))
        return unique[:k] if k else fallback
    except _HTTP_ERRORS:
        # on any error, soft-fallback to cache or all the way to fallback
        if _SYMBOL_CACHE:
            k = min(limit, len(_SYMBOL_CACHE))
            return list(_SYMBOL_CACHE)[:k]
        return fallback[:limit]


def env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except _ENV_ERRORS:
        return default


def env_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except _ENV_ERRORS:
        return default


def env_b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on", "y"}


class CircuitBreaker:
    """Fast-fail circuit breaker that pauses trading on repeated errors."""

    def __init__(self, err_threshold: int = 4, window_sec: int = 30, cooldown_sec: int = 120):
        self.err_threshold = err_threshold
        self.window_sec = window_sec
        self.cooldown_sec = cooldown_sec
        self._events: deque[float] = deque()
        self._cool_until = 0.0

    def record_error(self) -> None:
        now = time.time()
        cutoff = now - self.window_sec
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        self._events.append(now)
        if len(self._events) >= self.err_threshold:
            self._cool_until = now + self.cooldown_sec
            self._events.clear()

    @property
    def open(self) -> bool:
        return time.time() < self._cool_until

    @property
    def cool_left(self) -> int:
        return max(0, int(self._cool_until - time.time()))


class RateLimiter:
    """Simple sliding-window limiter (events per minute)."""

    def __init__(self, max_per_min: int) -> None:
        self.max_per_min = max_per_min
        self.events: deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        cutoff = now - 60.0
        while self.events and self.events[0] < cutoff:
            self.events.popleft()
        if len(self.events) >= self.max_per_min:
            return False
        self.events.append(now)
        return True


async def get_universe(engine_base: str) -> list[str]:
    # Try engine universe first, else fall back to OPS if present
    urls = [
        f"{engine_base}/universe",
        os.getenv("OPS_BASE", "http://localhost:8002").rstrip("/") + "/aggregate/universe",
    ]
    async with httpx.AsyncClient(timeout=6.0) as client:
        for u in urls:
            try:
                r = await client.get(u)
                r.raise_for_status()
                data = r.json()
                syms = data.get("symbols") or data.get("spot_usdt") or []
                if syms:
                    # Normalize to Binance spot style w/o venue suffix
                    out = []
                    for s in syms:
                        s = s.split(".")[0]
                        if s.endswith("USDT"):
                            out.append(s)
                    return out
            except _HTTP_ERRORS:
                continue
    return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


async def symbol_info(engine_base: str, symbol: str) -> dict:
    """Fetch symbol filters from engine; fall back gracefully on error.

    If /symbol_info returns 400/404 or is unavailable, attempt to read
    /risk/config for a global min_notional_usdt and synthesize a minimal
    filter so callers can proceed without crashing.
    """
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{engine_base}/symbol_info", params={"symbol": symbol})
            if r.status_code == 200:
                return r.json()
    except _HTTP_ERRORS:
        pass

    # Fallback: query risk config for a global min_notional
    min_notional = 5.0
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            rc = await client.get(f"{engine_base}/risk/config")
            if rc.status_code == 200:
                cfg = rc.json()
                mn = cfg.get("min_notional_usdt")
                if isinstance(mn, (int, float)):
                    min_notional = float(mn)
    except _HTTP_ERRORS:
        pass

    # Synthesize defaults; step sizes are conservative
    return {
        "symbol": symbol,
        "step_size": 0.000001,
        "min_qty": 0.0,
        "min_notional": float(min_notional),
        "max_notional": float("inf"),
        "tick_size": 0.0,
    }


async def fetch_all_prices(
    engine_base: str, client: httpx.AsyncClient | None = None
) -> dict[str, float]:
    """Fetch all prices in one batch call - reuse client if provided."""
    try:
        # Use provided client or create a temporary one
        temp_client = client is None
        if temp_client:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=2.0, read=4.0, write=4.0, pool=4.0),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
                trust_env=True,
            ) as client:
                r = await client.get(f"{engine_base}/prices")
                r.raise_for_status()
                data = r.json().get("prices", {})
        else:
            r = await client.get(f"{engine_base}/prices")
            r.raise_for_status()
            data = r.json().get("prices", {})

        # Normalize to floats
        return {k: float(v) for k, v in data.items()}
    except (TypeError, ValueError):
        return {}
    except _HTTP_ERRORS:
        return {}


async def submit_market_quote(
    client: httpx.AsyncClient,
    engine_base: str,
    symbol: str,
    side: str,
    quote: float,
    idem: str,
) -> dict:
    """Submit market order using shared client with exponential backoff retry on 429/5xx errors."""
    payload = {"symbol": symbol, "side": side, "quote": quote}

    # Backoff configuration from environment (already set in .env)
    base_backoff_ms = env_i("RETRY_BASE_MS", 600)  # 600ms default (as per user's config)
    backoff_multiplier = env_f("RETRY_BACKOFF", 2.0)  # 2x default
    max_backoff_sec = env_f("RETRY_MAX_SEC", 20.0)  # 20s max default

    backoff = base_backoff_ms / 1000.0  # Convert to seconds

    while True:
        try:
            r = await client.post(
                f"{engine_base}/orders/market",
                headers={"Content-Type": "application/json", "X-Idempotency-Key": idem},
                json=payload,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            # Retry on rate limits and server errors
            if status_code in (429, 500, 502, 503, 504):
                jitter = _RNG.uniform(0, backoff * 0.3)
                await asyncio.sleep(backoff + jitter)
                backoff = min(backoff * backoff_multiplier, max_backoff_sec)
                continue
            # Don't retry on client errors (4xx except 429)
            raise
        except httpx.RequestError:
            jitter = _RNG.uniform(0, backoff * 0.3)
            await asyncio.sleep(backoff + jitter)
            backoff = min(backoff * backoff_multiplier, max_backoff_sec)
            continue
        except _HTTP_ERRORS:
            # For network/other errors, still retry once with minimal backoff
            jitter = _RNG.uniform(0, backoff * 0.3)
            await asyncio.sleep(backoff + jitter)
            backoff = min(backoff * backoff_multiplier, max_backoff_sec)
            continue


async def probe_symbol(
    client: httpx.AsyncClient,
    engine_base: str,
    symbol: str,
    quote_usdt: float,
    slip_bps_max: float,
    cooldown_sec: int,
    limiter: RateLimiter,
    sem: asyncio.Semaphore,
    last_probe_ts: dict[str, float],
    dry_run: bool,
    price_map: dict[str, float],
    breaker: CircuitBreaker,
) -> dict:
    """Probe a symbol using shared client, batched prices, and circuit breaker protection."""
    now = time.time()

    # Circuit breaker guard - pause all trading when engine is stressed
    if breaker.open:
        return {"symbol": symbol, "skipped": f"breaker({breaker.cool_left}s)"}

    # Per-symbol cooldown
    if now - last_probe_ts.get(symbol, 0.0) < cooldown_sec:
        return {"symbol": symbol, "skipped": "cooldown"}

    info = await symbol_info(engine_base, symbol)
    min_notional = float(info.get("min_notional", 5.0))
    quote = max(quote_usdt, 1.1 * min_notional)

    # Global rate limit
    if not limiter.allow():
        return {"symbol": symbol, "skipped": "rate_limited"}

    async with sem:
        last = price_map.get(symbol)
        idem = f"probe:{symbol}:{int(now)}"

        if dry_run:
            last_probe_ts[symbol] = now
            return {
                "symbol": symbol,
                "status": "simulated",
                "quote": quote,
                "last": last,
            }

        try:
            # Use shared client
            res = await submit_market_quote(client, engine_base, symbol, "BUY", quote, idem)
            order = res.get("order", {})
            status = order.get("status") or res.get("status")
            avg_px = float(order.get("avg_fill_price") or 0.0)

            # Rough slippage check vs last price from batch fetch
            slip_bps = None
            if last and avg_px:
                slip_bps = abs(avg_px - last) / last * 10_000.0
            ok_slip = (slip_bps is None) or (slip_bps <= slip_bps_max)
        except _HTTP_ERRORS as exc:
            # Record error for circuit breaker
            breaker.record_error()
            last_probe_ts[symbol] = now
            return {"symbol": symbol, "error": str(exc), "quote": quote}
        else:
            last_probe_ts[symbol] = now
            return {
                "symbol": symbol,
                "status": status,
                "quote": quote,
                "avg_px": avg_px,
                "last": last,
                "slip_bps": slip_bps,
                "slip_ok": ok_slip,
            }


async def main():
    """Main trading loop with shared client and strictly bounded rounds."""
    ap = argparse.ArgumentParser(description="Auto probe many symbols via engine API")
    ap.add_argument("--engine", default=os.getenv("ENGINE_URL", "http://localhost:8003"))
    ap.add_argument("--symbols", default=os.getenv("SYMBOLS"))
    ap.add_argument("--probe-usdt", type=float, default=env_f("PROBE_USDT", 30.0))
    ap.add_argument("--max-slip-bps", type=float, default=env_f("MAX_SLIP_BP", 120.0))
    ap.add_argument("--max-orders-per-min", type=int, default=env_i("MAX_ORDERS_PER_MIN", 20))
    ap.add_argument("--max-parallel", type=int, default=env_i("MAX_PARALLEL_ORDERS", 3))
    ap.add_argument("--cooldown-sec", type=int, default=env_i("PROBE_COOLDOWN_SEC", 90))
    ap.add_argument("--rounds", type=int, default=99999, help="Infinite rounds unless specified")
    ap.add_argument("--dry-run", action="store_true", default=env_b("DRY_RUN", False))
    args = ap.parse_args()

    engine_base = args.engine.rstrip("/")
    symbols: list[str]
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = await get_universe(engine_base)

    if not symbols:
        print("No symbols to probe.")
        return

    # Initialize circuit breaker with environment settings
    breaker = CircuitBreaker(
        err_threshold=env_i("EXEC_ERR_THRESHOLD", 3),  # Trip on 3 errors
        window_sec=env_i("EXEC_ERR_WINDOW_SEC", 20),  # In 20 second window
        cooldown_sec=env_i("EXEC_COOLDOWN_SEC", 180),  # Cool down for 3 minutes
    )

    limiter = RateLimiter(args.max_orders_per_min)
    sem = asyncio.Semaphore(args.max_parallel)
    last_probe_ts: dict[str, float] = defaultdict(lambda: 0.0)

    # Create long-lived HTTP client with connection pooling
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=10)
    timeout = httpx.Timeout(connect=6.0, read=12.0, write=12.0, pool=12.0)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        for r in range(args.rounds):
            # Step 1: Fetch ALL prices in one round-trip (O(1) vs O(symbols))
            price_map = await fetch_all_prices(engine_base, client)

            # Step 2: Bound work per round (physically prevents storms)
            # - At most EXEC_SYMBOLS_PER_ROUND symbols processed per round
            # - Circuit breaker skips entire round if engine is hot
            # - Least-recently-probed symbols get priority
            max_per_round = env_i("EXEC_SYMBOLS_PER_ROUND", 1)
            pick = []
            for sym in sorted(symbols, key=lambda z: last_probe_ts.get(z, 0.0)):
                if len(pick) >= max_per_round:
                    break
                pick.append(sym)

            # Step 3: Only probe selected symbols (use shared client, batched prices)
            tasks = [
                probe_symbol(
                    client,
                    engine_base,
                    sym,
                    args.probe_usdt,
                    args.max_slip_bps,
                    args.cooldown_sec,
                    limiter,
                    sem,
                    last_probe_ts,
                    args.dry_run,
                    price_map,
                    breaker,
                )
                for sym in pick
            ]
            results = await asyncio.gather(*tasks)

            # Step 4: Compact round summary with breaker status
            ok = sum(1 for r in results if r.get("status") == "FILLED")
            errs = sum(1 for r in results if "error" in r)
            skipped = sum(1 for r in results if r.get("skipped"))
            print(
                {
                    "round": r + 1,
                    "symbols": len(pick),
                    "filled": ok,
                    "errors": errs,
                    "skipped": skipped,
                    "breaker": "open" if breaker.open else "closed",
                }
            )

            # Step 5: Pace rounds with jitter (prevents synchronization)
            base_interval = env_i("EXEC_INTERVAL_SEC", 12)
            jitter = env_f("EXEC_JITTER", 0.40)
            interval = base_interval * (1.0 + _RNG.uniform(-jitter, jitter))
            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
