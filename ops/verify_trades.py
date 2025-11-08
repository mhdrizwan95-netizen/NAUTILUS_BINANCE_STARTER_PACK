#!/usr/bin/env python3
"""
Quick venue verification: query Binance /api/v3/myTrades using the same
env/keys as the running container to prove whether fills are on-venue.

Usage (inside engine container):
  python -u ops/verify_trades.py BTCUSDT

Exits 0 on success. Prints status code and response body.
"""
import hashlib
import hmac
import os
import sys
import time
import urllib.parse

from ops.net import create_client, request_with_retry_sync


def main():
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT").upper()
    mode = (os.environ.get("BINANCE_MODE") or "").lower()
    if mode.startswith("futures"):
        base = os.environ.get("BINANCE_FUTURES_BASE") or "https://testnet.binancefuture.com"
        endpoint = "/fapi/v1/userTrades"
    else:
        base = (
            os.environ.get("DEMO_SPOT_BASE")
            or os.environ.get("BINANCE_SPOT_BASE")
            or "https://testnet.binance.vision"
        )
        endpoint = "/api/v3/myTrades"
    key = os.environ.get("BINANCE_API_KEY")
    sec = os.environ.get("BINANCE_API_SECRET")

    if not key or not sec:
        print("Missing BINANCE_API_KEY / BINANCE_API_SECRET in environment.")
        sys.exit(2)

    params = {
        "symbol": symbol,
        "timestamp": int(time.time() * 1000),
        "recvWindow": int(os.environ.get("BINANCE_RECV_WINDOW", "5000")),
    }
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = f"{base.rstrip('/')}{endpoint}?{qs}&signature={sig}"
    # Try up to 3 times, respect Retry-After if provided
    for attempt in range(3):
        with create_client() as client:
            r = request_with_retry_sync(
                client,
                "GET",
                url,
                headers={"X-MBX-APIKEY": key},
                retries=2,
                timeout=float(os.environ.get("BINANCE_API_TIMEOUT", "10")),
            )
        print(r.status_code, r.text[:500])
        if r.status_code == 429 and attempt < 2:
            try:
                ra = int(r.headers.get("Retry-After", "2"))
            except Exception:
                ra = 2
            time.sleep(max(1, ra))
            continue
        r.raise_for_status()
        break


if __name__ == "__main__":
    main()
