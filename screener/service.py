from __future__ import annotations

from fastapi import FastAPI, Response
import os, asyncio, time, random
from prometheus_client import CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time
import httpx

from .data import klines_1m, orderbook
from .features import compute_feats
from .alpha import score_long_short

APP = FastAPI(title="screener")
REG = CollectorRegistry()
G_SCORE = Gauge("screener_score", "score", ["symbol", "side"], registry=REG)
SCAN_LATENCY = Gauge("scan_latency_ms", "End-to-end scan latency (ms)", registry=REG)
SCAN_ERRORS = Gauge("scan_errors_total", "Total scan errors (best-effort)", registry=REG)
RATE_LIMIT_429 = Gauge("binance_429_total", "Binance HTTP 429 occurrences (best-effort)", registry=REG)

UNIVERSE_URL = "http://universe:8009/universe"
SITU_INGEST = "http://situations:8011/ingest/bar"


def get_universe():
    try:
        return httpx.get(UNIVERSE_URL, timeout=5).json()
    except Exception:
        return {}


@APP.get("/scan")
def scan():
    uni = get_universe()
    out = {"ts": int(time.time()), "long": [], "short": []}
    # Optional: symbol cap + rotation to stay under API quotas
    items = list(uni.items())
    cap = int(os.getenv("SCREENER_SYMBOL_CAP", "100"))
    rot = int(os.getenv("SCREENER_ROTATE", "1")) or 1
    cycle = int((time.time() // max(1, int(os.getenv("SCREENER_SCAN_INTERVAL_SEC", "60")))) % rot)
    if rot > 1:
        items = items[cycle::rot]
    if cap and len(items) > cap:
        items = items[:cap]

    t0 = time.time()
    errors = 0
    rate_limits = 0

    for sym, meta in items:
        try:
            kl = klines_1m(sym, n=60)
            ob = orderbook(sym, limit=10)
            # quick 429 / error heuristics
            if isinstance(kl, dict) and kl.get("code"):
                rate_limits += 1 if str(kl.get("code")) in {"-1003", "429"} else 0
                errors += 1
                continue
            if not isinstance(ob, dict) or "bids" not in ob or "asks" not in ob:
                errors += 1
                continue
            f = compute_feats(kl, ob)
            f["vwap_dev_prev"] = 0.0
            long, short = score_long_short(f)
            G_SCORE.labels(sym, "long").set(long)
            G_SCORE.labels(sym, "short").set(short)
            try:
                httpx.post(SITU_INGEST, json={"symbol": sym, "ts": out["ts"], "features": f}, timeout=2)
            except Exception:
                pass
            out["long"].append({"symbol": sym, "score": long})
            out["short"].append({"symbol": sym, "score": short})
        except Exception:
            errors += 1
            continue
    out["long"] = sorted(out["long"], key=lambda x: x["score"], reverse=True)[:5]
    out["short"] = sorted(out["short"], key=lambda x: x["score"], reverse=True)[:5]
    try:
        elapsed_ms = (time.time() - t0) * 1000.0
        SCAN_LATENCY.set(elapsed_ms)
        if errors:
            SCAN_ERRORS.set(errors)
        if rate_limits:
            RATE_LIMIT_429.set(rate_limits)
    except Exception:
        pass
    return out


@APP.get("/health")
def health():
    return {"ok": True}


@APP.get("/candidates")
def candidates(limit: int = 20):
    """
    Return candidate symbols for trading. Currently uses universe or fallbacks.
    Future: integrate scoring to return top candidates based on alpha signals.
    """
    # Try to get universe
    uni = get_universe()
    symbols = list(uni.keys()) if uni else []

    # Fallback to basic universe if universe service is down
    if not symbols:
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT",
                  "LINKUSDT", "XRPUSDT", "LTCUSDT", "BCHUSDT", "ETCUSDT"]

    # Limit to requested amount
    symbols = symbols[:limit] if limit > 0 else symbols

    # For now, return simple list of symbols
    # TODO: In future, rank by alpha scores from scan results
    return symbols


@APP.get("/metrics")
def metrics():
    payload = generate_latest(REG)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


# Optional: automatic periodic scans to keep hits flowing (toggle via env)
@APP.on_event("startup")
async def _auto_scan():
    enabled = os.getenv("SCREENER_AUTO_SCAN", "").lower() in {"1", "true", "yes"}
    if not enabled:
        return

    interval = int(os.getenv("SCREENER_SCAN_INTERVAL_SEC", "60"))
    jitter = float(os.getenv("SCREENER_SCAN_JITTER", "0.1"))  # ±10%
    _breaker = {"penalty": 1.0, "strike": 0}

    async def loop():
        await asyncio.sleep(5)
        while True:
            try:
                # Run a synchronous scan; it will post hits to situations
                before = time.time()
                res = scan()
                # crude rate-limit detection from last call
                rl = 0
                try:
                    rl = int(RATE_LIMIT_429._value.get())  # type: ignore[attr-defined]
                except Exception:
                    rl = 0
                if rl > 0:
                    _breaker["strike"] += 1
                    _breaker["penalty"] = min(_breaker["penalty"] * 1.5, 6.0)
                else:
                    _breaker["strike"] = max(0, _breaker["strike"] - 1)
                    if _breaker["strike"] == 0:
                        _breaker["penalty"] = max(1.0, _breaker["penalty"] * 0.9)
            except Exception:
                _breaker["strike"] += 1
            # backoff + jitter
            elapsed = max(0.0, time.time() - before)
            sleep_base = max(5.0, interval - elapsed)
            sleep_scaled = sleep_base * _breaker["penalty"]
            factor = random.uniform(1 - jitter, 1 + jitter)
            await asyncio.sleep(sleep_scaled * factor)

    asyncio.create_task(loop())


# Optional control endpoints to toggle auto-scan at runtime
_AUTO_SCAN_CTL = {"enabled": os.getenv("SCREENER_AUTO_SCAN", "").lower() in {"1","true","yes"}}

@APP.get("/control/scan")
def scan_status():
    return {"enabled": _AUTO_SCAN_CTL["enabled"], "interval_sec": int(os.getenv("SCREENER_SCAN_INTERVAL_SEC", "60"))}

@APP.post("/control/scan")
def scan_control(body: dict):
    en = bool(body.get("enabled", True))
    _AUTO_SCAN_CTL["enabled"] = en
    # toggle requires restart for now; endpoint is a placeholder for UI wiring
    return {"ok": True, "enabled": en}
