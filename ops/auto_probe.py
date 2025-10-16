from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections import deque, defaultdict
from typing import Deque, Dict, List, Optional

import httpx


def env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def env_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def env_b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on", "y"}


class RateLimiter:
    """Simple sliding-window limiter (events per minute)."""

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


async def get_universe(engine_base: str) -> List[str]:
    # Try engine universe first, else fall back to OPS if present
    urls = [f"{engine_base}/universe", os.getenv("OPS_BASE", "http://localhost:8002").rstrip("/") + "/aggregate/universe"]
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
            except Exception:
                continue
    return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


async def symbol_info(engine_base: str, symbol: str) -> dict:
    async with httpx.AsyncClient(timeout=6.0) as client:
        r = await client.get(f"{engine_base}/symbol_info", params={"symbol": symbol})
        r.raise_for_status()
        return r.json()


async def last_price(engine_base: str, symbol: str) -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{engine_base}/prices")
            r.raise_for_status()
            p = r.json().get("prices", {})
            return float(p.get(symbol)) if symbol in p else None
    except Exception:
        return None


async def submit_market_quote(engine_base: str, symbol: str, side: str, quote: float, idem: str) -> dict:
    payload = {"symbol": symbol, "side": side, "quote": quote}
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.post(
            f"{engine_base}/orders/market",
            headers={"Content-Type": "application/json", "X-Idempotency-Key": idem},
            json=payload,
        )
        r.raise_for_status()
        return r.json()


async def probe_symbol(
    engine_base: str,
    symbol: str,
    quote_usdt: float,
    slip_bps_max: float,
    cooldown_sec: int,
    limiter: RateLimiter,
    sem: asyncio.Semaphore,
    last_probe_ts: Dict[str, float],
    dry_run: bool,
) -> dict:
    now = time.time()
    if now - last_probe_ts.get(symbol, 0.0) < cooldown_sec:
        return {"symbol": symbol, "skipped": "cooldown"}

    info = await symbol_info(engine_base, symbol)
    min_notional = float(info.get("min_notional", 5.0))
    quote = max(quote_usdt, 1.1 * min_notional)

    if not limiter.allow():
        return {"symbol": symbol, "skipped": "rate_limited"}

    async with sem:
        last = await last_price(engine_base, symbol)
        idem = f"probe:{symbol}:{int(now)}"
        if dry_run:
            last_probe_ts[symbol] = now
            return {"symbol": symbol, "status": "simulated", "quote": quote, "last": last}

        try:
            res = await submit_market_quote(engine_base, symbol, "BUY", quote, idem)
            order = res.get("order", {})
            status = order.get("status") or res.get("status")
            avg_px = float(order.get("avg_fill_price") or 0.0)
            # Rough slippage check vs last
            slip_bps = None
            if last and avg_px:
                slip_bps = abs(avg_px - last) / last * 10_000.0
            ok_slip = (slip_bps is None) or (slip_bps <= slip_bps_max)
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
        except Exception as e:
            last_probe_ts[symbol] = now
            return {"symbol": symbol, "error": str(e), "quote": quote}


async def main():
    ap = argparse.ArgumentParser(description="Auto probe many symbols via engine API")
    ap.add_argument("--engine", default=os.getenv("ENGINE_URL", "http://localhost:8003"))
    ap.add_argument("--symbols", default=os.getenv("SYMBOLS"))
    ap.add_argument("--probe-usdt", type=float, default=env_f("PROBE_USDT", 30.0))
    ap.add_argument("--max-slip-bps", type=float, default=env_f("MAX_SLIP_BP", 120.0))
    ap.add_argument("--max-orders-per-min", type=int, default=env_i("MAX_ORDERS_PER_MIN", 20))
    ap.add_argument("--max-parallel", type=int, default=env_i("MAX_PARALLEL_ORDERS", 3))
    ap.add_argument("--cooldown-sec", type=int, default=env_i("PROBE_COOLDOWN_SEC", 90))
    ap.add_argument("--rounds", type=int, default=1, help="How many passes to run over the list")
    ap.add_argument("--dry-run", action="store_true", default=env_b("DRY_RUN", False))
    args = ap.parse_args()

    engine_base = args.engine.rstrip("/")
    symbols: List[str]
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = await get_universe(engine_base)

    if not symbols:
        print("No symbols to probe.")
        return

    limiter = RateLimiter(args.max_orders_per_min)
    sem = asyncio.Semaphore(args.max_parallel)
    last_probe_ts: Dict[str, float] = defaultdict(lambda: 0.0)

    for r in range(args.rounds):
        tasks = [
            probe_symbol(
                engine_base,
                sym,
                args.probe_usdt,
                args.max_slip_bps,
                args.cooldown_sec,
                limiter,
                sem,
                last_probe_ts,
                args.dry_run,
            )
            for sym in symbols
        ]
        results = await asyncio.gather(*tasks)
        # Compact summary per round
        ok = sum(1 for r in results if r.get("status") == "FILLED")
        errs = sum(1 for r in results if "error" in r)
        skipped = sum(1 for r in results if r.get("skipped"))
        print({"round": r + 1, "symbols": len(symbols), "filled": ok, "errors": errs, "skipped": skipped})


if __name__ == "__main__":
    asyncio.run(main())

