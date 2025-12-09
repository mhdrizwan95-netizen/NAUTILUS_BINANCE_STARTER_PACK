"""Sample momentum breakout strategy for backtesting."""

from dataclasses import dataclass

from .driver import Bar


@dataclass
class Signal:
    """Trading signal from strategy."""
    symbol: str
    side: str  # "BUY", "SELL", "HOLD"
    strength: float  # 0.0 to 1.0
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""


class MomentumStrategy:
    """Simple momentum breakout strategy.
    
    Generates signals based on:
    - Price momentum over lookback period
    - Volume confirmation
    - Range breakout
    """
    
    def __init__(
        self,
        lookback: int = 20,
        momentum_threshold: float = 0.02,
        volume_ratio: float = 1.5,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
    ):
        """Initialize the strategy.
        
        Args:
            lookback: Bars to look back for momentum calculation
            momentum_threshold: Minimum momentum for signal (2% default)
            volume_ratio: Required volume ratio vs average
            stop_loss_pct: Stop loss percentage
            take_profit_pct: Take profit percentage
        """
        self.lookback = lookback
        self.momentum_threshold = momentum_threshold
        self.volume_ratio = volume_ratio
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # State
        self.bar_history: dict[str, list[Bar]] = {}
    
    def on_bar(self, bar: Bar) -> Signal | None:
        """Process a new bar and generate signal.
        
        Args:
            bar: OHLCV bar data
            
        Returns:
            Signal if conditions met, None otherwise
        """
        symbol = bar.symbol
        
        # Initialize history
        if symbol not in self.bar_history:
            self.bar_history[symbol] = []
        
        history = self.bar_history[symbol]
        history.append(bar)
        
        # Keep only lookback + buffer
        if len(history) > self.lookback + 10:
            self.bar_history[symbol] = history[-self.lookback - 10:]
            history = self.bar_history[symbol]
        
        # Need enough history
        if len(history) < self.lookback:
            return None
        
        # Compute momentum
        lookback_bars = history[-self.lookback:]
        first_close = lookback_bars[0].close
        last_close = lookback_bars[-1].close
        
        if first_close <= 0:
            return None
        
        momentum = (last_close - first_close) / first_close
        
        # Compute volume ratio
        avg_volume = sum(b.volume for b in lookback_bars[:-1]) / (len(lookback_bars) - 1)
        current_volume = bar.volume
        
        if avg_volume <= 0:
            vol_ratio = 1.0
        else:
            vol_ratio = current_volume / avg_volume
        
        # Check for breakout
        recent_high = max(b.high for b in lookback_bars[:-1])
        recent_low = min(b.low for b in lookback_bars[:-1])
        
        # Generate signals
        if momentum > self.momentum_threshold and vol_ratio > self.volume_ratio:
            if bar.close > recent_high:
                # Bullish breakout
                return Signal(
                    symbol=symbol,
                    side="BUY",
                    strength=min(momentum / self.momentum_threshold, 1.0),
                    stop_loss=bar.close * (1 - self.stop_loss_pct),
                    take_profit=bar.close * (1 + self.take_profit_pct),
                    reason=f"Bullish breakout: momentum={momentum:.3f}, vol_ratio={vol_ratio:.2f}",
                )
        
        elif momentum < -self.momentum_threshold and vol_ratio > self.volume_ratio:
            if bar.close < recent_low:
                # Bearish breakout
                return Signal(
                    symbol=symbol,
                    side="SELL",
                    strength=min(abs(momentum) / self.momentum_threshold, 1.0),
                    stop_loss=bar.close * (1 + self.stop_loss_pct),
                    take_profit=bar.close * (1 - self.take_profit_pct),
                    reason=f"Bearish breakout: momentum={momentum:.3f}, vol_ratio={vol_ratio:.2f}",
                )
        
        return None
    
    def reset(self) -> None:
        """Reset strategy state."""
        self.bar_history.clear()


class TrendFollowStrategy:
    """Trend following strategy using moving averages.
    
    Generates signals based on:
    - Fast/slow MA crossover
    - Trend strength (slope of MA)
    - ATR-based stops
    """
    
    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 3.0,
        min_trend_strength: float = 0.001,
    ):
        """Initialize the strategy.
        
        Args:
            fast_period: Fast moving average period
            slow_period: Slow moving average period
            atr_period: ATR calculation period
            atr_stop_mult: ATR multiplier for stop loss
            atr_target_mult: ATR multiplier for take profit
            min_trend_strength: Minimum MA slope for signal
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult
        self.min_trend_strength = min_trend_strength
        
        # State
        self.bar_history: dict[str, list[Bar]] = {}
        self.prev_position: dict[str, str] = {}  # "LONG", "SHORT", "FLAT"
    
    def on_bar(self, bar: Bar) -> Signal | None:
        """Process a new bar and generate signal."""
        symbol = bar.symbol
        
        if symbol not in self.bar_history:
            self.bar_history[symbol] = []
            self.prev_position[symbol] = "FLAT"
        
        history = self.bar_history[symbol]
        history.append(bar)
        
        # Keep enough history
        max_period = max(self.slow_period, self.atr_period) + 10
        if len(history) > max_period:
            self.bar_history[symbol] = history[-max_period:]
            history = self.bar_history[symbol]
        
        if len(history) < self.slow_period:
            return None
        
        # Compute MAs
        closes = [b.close for b in history]
        fast_ma = sum(closes[-self.fast_period:]) / self.fast_period
        slow_ma = sum(closes[-self.slow_period:]) / self.slow_period
        
        # Compute ATR
        tr_values = []
        for i in range(1, min(self.atr_period + 1, len(history))):
            high = history[-i].high
            low = history[-i].low
            prev_close = history[-i - 1].close if i < len(history) else history[-i].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
        
        atr = sum(tr_values) / len(tr_values) if tr_values else bar.close * 0.02
        
        # Compute trend strength (slope of slow MA)
        if len(history) >= self.slow_period + 5:
            prev_slow_ma = sum(closes[-self.slow_period - 5:-5]) / self.slow_period
            trend_strength = (slow_ma - prev_slow_ma) / slow_ma if slow_ma > 0 else 0
        else:
            trend_strength = 0
        
        # Check for crossover
        prev_position = self.prev_position[symbol]
        
        if fast_ma > slow_ma and trend_strength > self.min_trend_strength:
            if prev_position != "LONG":
                self.prev_position[symbol] = "LONG"
                return Signal(
                    symbol=symbol,
                    side="BUY",
                    strength=min(abs(trend_strength) / self.min_trend_strength, 1.0),
                    stop_loss=bar.close - atr * self.atr_stop_mult,
                    take_profit=bar.close + atr * self.atr_target_mult,
                    reason=f"Bullish MA crossover: fast={fast_ma:.2f}, slow={slow_ma:.2f}",
                )
        
        elif fast_ma < slow_ma and trend_strength < -self.min_trend_strength:
            if prev_position != "SHORT":
                self.prev_position[symbol] = "SHORT"
                return Signal(
                    symbol=symbol,
                    side="SELL",
                    strength=min(abs(trend_strength) / self.min_trend_strength, 1.0),
                    stop_loss=bar.close + atr * self.atr_stop_mult,
                    take_profit=bar.close - atr * self.atr_target_mult,
                    reason=f"Bearish MA crossover: fast={fast_ma:.2f}, slow={slow_ma:.2f}",
                )
        
        # Reset position when MAs converge
        if abs(fast_ma - slow_ma) / slow_ma < 0.001:
            self.prev_position[symbol] = "FLAT"
        
        return None
    
    def reset(self) -> None:
        """Reset strategy state."""
        self.bar_history.clear()
        self.prev_position.clear()
