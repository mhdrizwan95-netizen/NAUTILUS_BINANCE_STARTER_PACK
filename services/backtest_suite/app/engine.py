"""Main backtest engine implementing prequential evaluation."""

from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from .clock import SimulationClock
from .config import settings
from .driver import Bar, DataDriver
from .execution import ExecutionModel, Portfolio
from .metrics import MetricsCollector, TradeRecord
from .strategies import MomentumStrategy, Signal, TrendFollowStrategy


class BacktestEngine:
    """Prequential backtesting engine.
    
    Implements test-then-train evaluation where:
    - At time t, model used is trained on data up to t-1
    - Retraining happens on configurable cadence
    - Parameters can be fetched from param controller
    """
    
    def __init__(
        self,
        symbols: list[str] | None = None,
        strategy: str = "momentum",
        initial_equity: float = 10000.0,
    ):
        """Initialize the backtest engine.
        
        Args:
            symbols: Symbols to trade (None = all available)
            strategy: Strategy type ("momentum" or "trend_follow")
            initial_equity: Starting portfolio equity
        """
        self.symbols = symbols
        self.strategy_type = strategy
        self.initial_equity = initial_equity
        
        # Components
        self.driver = DataDriver(symbols)
        self.execution = ExecutionModel()
        self.portfolio = Portfolio(cash=initial_equity)
        self.metrics = MetricsCollector(initial_equity)
        self.clock: SimulationClock | None = None
        
        # Strategy
        self._init_strategy()
        
        # State
        self.current_positions: dict[str, dict] = {}  # symbol -> position info
        self.last_retrain_ts: int = 0
        self.run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    def _init_strategy(self) -> None:
        """Initialize the trading strategy."""
        if self.strategy_type == "trend_follow":
            self.strategy = TrendFollowStrategy()
        else:
            self.strategy = MomentumStrategy()
    
    def load_data(self) -> int:
        """Load historical data.
        
        Returns:
            Number of bars loaded
        """
        # Try historical dir first, then incoming
        bars = self.driver.load_historical()
        if bars == 0:
            bars = self.driver.load_from_incoming()
        
        if bars > 0:
            start, end = self.driver.get_time_range()
            step_ms = settings.STEP_MINUTES * 60 * 1000
            self.clock = SimulationClock(start, end, step_ms)
            logger.info(
                f"Loaded {bars} bars for {len(self.driver.get_symbols())} symbols, "
                f"time range: {datetime.fromtimestamp(start/1000)} to {datetime.fromtimestamp(end/1000)}"
            )
        
        return bars
    
    def run(self) -> dict[str, Any]:
        """Run the backtest simulation.
        
        Returns:
            Dict with results including metrics
        """
        if self.clock is None:
            bars = self.load_data()
            if bars == 0:
                logger.error("No data loaded, cannot run backtest")
                return {"error": "No data loaded"}
        
        symbols = self.driver.get_symbols()
        if not symbols:
            return {"error": "No symbols available"}
        
        logger.info(f"Starting backtest with {len(symbols)} symbols")
        logger.info(f"Strategy: {self.strategy_type}, Initial equity: {self.initial_equity}")
        
        step = 0
        for ts in self.clock.iter_steps():
            # Get current bars for all symbols
            current_bars: dict[str, Bar] = {}
            for symbol in symbols:
                bar = self.driver.get_bar_at(symbol, ts)
                if bar:
                    current_bars[symbol] = bar
            
            if not current_bars:
                continue
            
            # Check for retraining
            if self._should_retrain(ts):
                self._trigger_retrain()
            
            # Process each symbol
            for symbol, bar in current_bars.items():
                # Generate signal
                signal = self.strategy.on_bar(bar)
                
                if signal:
                    self._process_signal(signal, bar, ts)
            
            # Mark to market
            prices = {s: b.close for s, b in current_bars.items()}
            self.execution.mark_to_market(self.portfolio, prices)
            
            # Record equity
            self._record_equity(ts)
            
            # Progress logging
            step += 1
            if step % 1000 == 0:
                progress = self.clock.progress() * 100
                logger.info(
                    f"Progress: {progress:.1f}%, "
                    f"Equity: ${self.portfolio.equity:.2f}, "
                    f"Trades: {self.portfolio.trade_count}"
                )
        
        # Compute final metrics
        metrics = self.metrics.compute_metrics()
        
        # Save results
        self.metrics.save_results(settings.RESULTS_DIR, self.run_id)
        
        logger.info(f"Backtest complete: {metrics.total_trades} trades")
        logger.info(f"Total return: {metrics.total_return:.2%}")
        logger.info(f"Sharpe ratio: {metrics.sharpe_ratio:.3f}")
        logger.info(f"Max drawdown: {metrics.max_drawdown:.2%}")
        
        return {
            "run_id": self.run_id,
            "metrics": metrics.to_dict(),
            "symbols": symbols,
            "bars_processed": step,
        }
    
    def _should_retrain(self, ts: int) -> bool:
        """Check if model should be retrained."""
        retrain_interval_ms = settings.RETRAIN_EVERY_MIN * 60 * 1000
        return ts - self.last_retrain_ts >= retrain_interval_ms
    
    def _trigger_retrain(self) -> None:
        """Trigger model retraining via ML service."""
        try:
            response = httpx.post(
                f"{settings.ML_SERVICE}/train",
                json={"n_states": 3, "tag": "backtest", "promote": False},
                timeout=30.0,
            )
            if response.status_code == 200:
                logger.info(f"Model retrained: {response.json()}")
            self.last_retrain_ts = self.clock.now() if self.clock else 0
        except Exception as e:
            logger.warning(f"Retrain failed: {e}")
    
    def _fetch_params(self, strategy: str, symbol: str) -> dict[str, Any]:
        """Fetch parameters from param controller."""
        try:
            response = httpx.get(
                f"{settings.PARAM_CONTROLLER}/param/{strategy}/{symbol}",
                timeout=5.0,
            )
            if response.status_code == 200:
                return response.json().get("params", {})
        except Exception:
            pass
        return {}
    
    def _process_signal(self, signal: Signal, bar: Bar, ts: int) -> None:
        """Process a trading signal."""
        symbol = signal.symbol
        
        # Check current position
        current_pos = self.portfolio.positions.get(symbol)
        has_position = current_pos and current_pos.is_open()
        
        # Position sizing (fixed percentage)
        position_size = self.portfolio.equity * 0.1  # 10% per trade
        quantity = position_size / bar.close
        
        # Compute volatility for slippage
        volatility = self.driver.compute_volatility(symbol, 20)
        
        if signal.side == "BUY":
            if not has_position or current_pos.quantity < 0:
                # Close short if exists
                if has_position and current_pos.quantity < 0:
                    self._close_position(symbol, bar, ts)
                
                # Open long
                fill = self.execution.execute(
                    self.portfolio, ts, symbol, "BUY", quantity, bar.close, volatility
                )
                if fill:
                    self.current_positions[symbol] = {
                        "entry_ts": ts,
                        "entry_price": fill.price,
                        "side": "LONG",
                        "stop_loss": signal.stop_loss,
                        "take_profit": signal.take_profit,
                    }
        
        elif signal.side == "SELL":
            if has_position and current_pos.quantity > 0:
                # Close long
                self._close_position(symbol, bar, ts)
            
            # Could open short here if desired
    
    def _close_position(self, symbol: str, bar: Bar, ts: int) -> None:
        """Close an open position."""
        pos = self.portfolio.positions.get(symbol)
        if not pos or not pos.is_open():
            return
        
        volatility = self.driver.compute_volatility(symbol, 20)
        
        if pos.quantity > 0:
            fill = self.execution.execute(
                self.portfolio, ts, symbol, "SELL", pos.quantity, bar.close, volatility
            )
        else:
            fill = self.execution.execute(
                self.portfolio, ts, symbol, "BUY", abs(pos.quantity), bar.close, volatility
            )
        
        if fill and symbol in self.current_positions:
            entry = self.current_positions[symbol]
            trade = TradeRecord(
                entry_timestamp=entry["entry_ts"],
                exit_timestamp=ts,
                symbol=symbol,
                side=entry["side"],
                entry_price=entry["entry_price"],
                exit_price=fill.price,
                quantity=fill.quantity,
                pnl=pos.realized_pnl,
                fees=fill.fee,
                holding_period_ms=ts - entry["entry_ts"],
            )
            self.metrics.record_trade(trade)
            del self.current_positions[symbol]
    
    def _record_equity(self, ts: int) -> None:
        """Record current equity state."""
        total_realized = sum(
            p.realized_pnl for p in self.portfolio.positions.values()
        )
        total_unrealized = sum(
            p.unrealized_pnl for p in self.portfolio.positions.values()
        )
        
        self.metrics.record_equity(
            timestamp=ts,
            equity=self.portfolio.equity,
            cash=self.portfolio.cash,
            exposure=self.portfolio.exposure,
            unrealized_pnl=total_unrealized,
            realized_pnl=total_realized,
        )
