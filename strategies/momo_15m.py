from collections import deque
import time

class Momentum15m:
    def __init__(self, engine, symbol="PI_XBTUSD", lookback=60):  # 60 ticks ~ 15m if 15s tick cadence
        self.engine = engine
        self.symbol = symbol
        self.last = None
        self.window = deque(maxlen=lookback)

    def on_tick(self, price: float, ts: float):
        self.window.append(price)
        self.last = price
        if len(self.window) < self.window.maxlen:
            return
        lo, hi = min(self.window), max(self.window)
        # naive breakout: buy if near high, flatten if near low
        pos = self.engine.position(self.symbol) or 0
        if price >= hi and pos <= 0:
            self.engine.market_buy(self.symbol, qty=1)
        elif price <= lo and pos > 0:
            self.engine.market_sell(self.symbol, qty=pos)
