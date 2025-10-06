# M8: run_live.py (Binance Spot live tiny size)
import os
from dotenv import load_dotenv

def main():
    load_dotenv()
    symbol = os.getenv("SYMBOL", "BTCUSDT.BINANCE")
    print(f"[M8] LIVE engine for {symbol} on Binance Spot (qty tiny).")
    # TODO M8: flip to live endpoints, verify keys, instantiate clients/strategy, start engine

if __name__ == "__main__":
    main()
