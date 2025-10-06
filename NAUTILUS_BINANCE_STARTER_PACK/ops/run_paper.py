# M1: run_paper.py (Binance Spot testnet)
import os
from dotenv import load_dotenv
from strategies.hmm_policy.config import HMMPolicyConfig

def main():
    load_dotenv()
    symbol = os.getenv("SYMBOL", "BTCUSDT.BINANCE")
    print(f"[M1] Starting paper engine for {symbol} on Binance Spot Testnet")
    # TODO M1: Instantiate Binance data/execution clients (testnet) and HMMPolicyStrategy
    # TODO M1: Subscribe to L2 + trades and start event loop

if __name__ == "__main__":
    main()
