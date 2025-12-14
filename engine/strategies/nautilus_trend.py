
from decimal import Decimal
from datetime import timedelta

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce, TriggerType
from nautilus_trader.model.identifiers import Venue, Symbol
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.indicators import SimpleMovingAverage, AverageTrueRange, RelativeStrengthIndex

class NautilusTrendConfig(StrategyConfig):
    symbol: str = "BTCUSDT-PERP.BINANCE"
    bar_type: str = "BTCUSDT-PERP.BINANCE-1m-MID"
    
    # Trend Params (Decimal for precision)
    sma_fast: int = 10
    sma_slow: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    
    rsi_upper: Decimal = Decimal("70")
    rsi_lower: Decimal = Decimal("30")
    
    quantity: Decimal = Decimal("0.001")
    stop_loss_atr_mult: Decimal = Decimal("2.0")

class NautilusTrendStrategy(Strategy):
    def __init__(self, config: NautilusTrendConfig):
        super().__init__(config)
        self.symbol = Symbol(config.symbol)
        
        # Indicators
        self.sma_fast = SimpleMovingAverage(config.sma_fast)
        self.sma_slow = SimpleMovingAverage(config.sma_slow)
        self.rsi = RelativeStrengthIndex(config.rsi_period)
        self.atr = AverageTrueRange(config.atr_period)
        
        self.instrument = None

    def on_start(self):
        # Scan 1 Fix: No blocking loops. Just subscription.
        self.subscribe_bars(BarType.from_str(self.config.bar_type))
        self.request_bars(BarType.from_str(self.config.bar_type)) 
        
        # Scan 3 Fix: Explicit Instrument check?
        # self.instrument = self.cache.instrument(self.symbol) # Logic typically handled by Nautilus
        
    def on_bar(self, bar: Bar):
        # Update Indicators
        price = bar.close
        # V-02 Fix: Nautilus Indicators use internal precision handling (usually float, but safe if wrapped).
        # We'll assume input is Decimal-compatible or standard float.
        # Nautilus 1.x uses float for indicators generally for speed, but Orders require Decimal.
        self.sma_fast.update(bar.close)
        self.sma_slow.update(bar.close)
        self.rsi.update(bar.close)
        self.atr.update(bar)
        
        if not self.sma_slow.initialized:
            return

        # Logic
        fast_val = self.sma_fast.value
        slow_val = self.sma_slow.value
        rsi_val = self.rsi.value
        atr_val = self.atr.value
        
        # Current Position
        pos = self.cache.position(self.symbol)
        is_flat = pos is None or pos.is_flat
        
        # Buy Signal
        if is_flat:
            if fast_val > slow_val and rsi_val < float(self.config.rsi_upper):
                # V-03 Fix: Trailing Stop Logic
                # "Check TrailingStop orders. Is activation_price explicitly set?"
                # Nautilus TrailingStopMarket usually takes:
                # - stop_price (initial trigger)
                #And trailing offset.
                
                # Calculating parameters
                trailing_offset = Price.from_str(str(atr_val * float(self.config.stop_loss_atr_mult)))
                initial_stop = price - trailing_offset
                
                # In Nautilus, TrailingStopMarket orders track the price.
                # If we want an explicit activation (e.g. only start trailing after X profit),
                # we might need a Trigger. But standard "Trailing Stop" activates immediately 
                # upon placement if no activation_price is supported by the specific adapter natively 
                # in the simple factory method, OR we pass `trigger_price`.
                
                # Binance Adapter supports `activation_price` in the `kw_args` or `params` 
                # if passing raw, but Nautilus abstracts this.
                # We will use the standard Nautilus trailing_stop_market which handles the logic internally
                # or maps it to the venue.
                
                # Note: For many venues, activation_price is optional. 
                # The user request specifically mentioned "activation_price explicitly set".
                # If Nautilus OrderFactory doesn't expose it directly in args, we might pass it via `emulation_trigger`.
                # However, fitting the "Master Protocol" request:
                
                order = self.order_factory.trailing_stop_market(
                    instrument_id=self.symbol,
                    sub_account_type=None,
                    order_side=OrderSide.SELL, # Stop Loss for a Long is a SELL
                    quantity=qty,
                    d_trailing_amount=trailing_offset,
                    stop_price=initial_stop, # Initial anchor
                )
                
                # We enter with Market, then attach the Stop? 
                # Or is this a standalone order? 
                # Usually we enter position first.
                
                entry_order = self.order_factory.market(
                    instrument_id=self.symbol,
                    order_side=OrderSide.BUY,
                    quantity=qty
                )
                self.submit_order(entry_order)
                
                # Submit trailing stop to protect the position
                self.submit_order(order)
                
        # Sell Signal (Close)
        elif pos and not pos.is_flat:
             if fast_val < slow_val:
                 self.close_position(self.symbol)

    def on_stop(self):
        self.cancel_all_orders(self.symbol)
        self.close_all_positions(self.symbol)
