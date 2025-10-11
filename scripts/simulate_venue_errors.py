#!/usr/bin/env python3
"""
Simulate venue error-rate to trip the breaker:
- Sends N OKs and M errors to risk.record_result via a temporary endpoint (or call your wrapper with forced exceptions).
Simplest: just hit /orders/market with a symbol that your venue wrapper is patched to fail for.
"""
import time, requests, sys, json, random

ENGINE="http://localhost:8003"

def main():
    # Try 20 calls with 60% failures (you can patch your exchange wrapper to raise on SYMBOL=FAIL.BINANCE)
    for i in range(20):
        sym = "BTCUSDT.BINANCE" if random.random() > 0.6 else "FAIL.BINANCE"
        try:
            r = requests.post(f"{ENGINE}/orders/market",
                headers={"content-type":"application/json"},
                data=json.dumps({"symbol": sym, "side":"BUY", "quote":5}))
            print(i, sym, r.status_code)
        except Exception as e:
            print("exc", e)
        time.sleep(0.3)

if __name__ == "__main__":
    main()
