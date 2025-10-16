#!/usr/bin/env python3
"""
IBKR Price Publisher for OPS
- Connects to IB Gateway/TWS via ib-insync
- Subscribes to quotes for watchlist tickers
- Exposes prices via Prometheus metrics
"""

import os, time, asyncio, logging
from ib_insync import IB, Stock, util
from prometheus_client import Gauge
from ops.prometheus import REGISTRY

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Default tickers — override via OPS_IBKR_TICKERS env
WATCHLIST = os.getenv("OPS_IBKR_TICKERS", "AAPL,MSFT,NVDA,TSLA,GOOGL").split(",")

# Programmatic price cache (updated alongside Prometheus metrics)
PRICES: dict[str, float] = {}

# Prometheus metrics
PRICE_METRICS = {
    sym: Gauge(
        f"ibkr_price_{sym.lower()}_usd",
        f"Last traded price for {sym} (USD)",
        registry=REGISTRY,
        multiprocess_mode="max",
    )
    for sym in WATCHLIST
}
LAST_UPDATE = Gauge(
    "ibkr_last_price_update_epoch",
    "Unix time of last IBKR price update",
    registry=REGISTRY,
    multiprocess_mode="max",
)

class IbkrPriceFeed:
    def __init__(self):
        self.host = os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = int(os.getenv("IBKR_PORT", "7497"))
        self.client_id = int(os.getenv("IBKR_CLIENT_ID", "888"))
        self.ib = IB()
        self.connected = False
        self.contracts = {}

    def connect(self):
        if not self.connected:
            self.ib.connect(self.host, self.port, clientId=self.client_id, readonly=True)
            logging.info(f"Connected to IBKR at {self.host}:{self.port} (client_id={self.client_id})")
            self.connected = True

    def subscribe(self, symbols):
        for sym in symbols:
            stock = Stock(sym, "SMART", "USD")
            cd = self.ib.reqMktData(stock, "", False, False)
            self.contracts[sym] = cd
            logging.info(f"Subscribed to {sym} market data")

    async def stream_prices(self, interval=1.0):
        while True:
            try:
                for sym, cd in list(self.contracts.items()):
                    last = cd.last if cd.last else cd.close
                    if last:
                        PRICE_METRICS[sym].set(float(last))
                        PRICES[sym.upper()] = float(last)
                LAST_UPDATE.set(time.time())
                await asyncio.sleep(interval)
            except Exception as e:
                logging.warning(f"Error updating prices: {e}")
                await asyncio.sleep(interval)

async def main():
    feed = IbkrPriceFeed()
    feed.connect()
    feed.subscribe(WATCHLIST)
    await feed.stream_prices()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
