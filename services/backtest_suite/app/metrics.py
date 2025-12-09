"""Performance metrics calculation for backtests."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class EquityPoint:
    """Single equity curve point."""
    timestamp: int
    equity: float
    cash: float
    exposure: float
    unrealized_pnl: float
    realized_pnl: float


@dataclass
class TradeRecord:
    """Record of a completed trade."""
    entry_timestamp: int
    exit_timestamp: int
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    fees: float
    holding_period_ms: int


@dataclass
class BacktestMetrics:
    """Comprehensive backtest performance metrics."""
    
    # Basic stats
    start_timestamp: int = 0
    end_timestamp: int = 0
    total_bars: int = 0
    total_trades: int = 0
    
    # Returns
    total_return: float = 0.0
    annual_return: float = 0.0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_ms: int = 0
    volatility: float = 0.0
    
    # Trade stats
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_holding_period_ms: int = 0
    
    # Costs
    total_fees: float = 0.0
    total_slippage: float = 0.0
    
    # Final state
    final_equity: float = 0.0
    peak_equity: float = 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "total_bars": self.total_bars,
            "total_trades": self.total_trades,
            "total_return": round(self.total_return, 4),
            "annual_return": round(self.annual_return, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "max_drawdown_duration_ms": self.max_drawdown_duration_ms,
            "volatility": round(self.volatility, 4),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 3),
            "avg_win": round(self.avg_win, 4),
            "avg_loss": round(self.avg_loss, 4),
            "avg_holding_period_ms": self.avg_holding_period_ms,
            "total_fees": round(self.total_fees, 2),
            "total_slippage": round(self.total_slippage, 2),
            "final_equity": round(self.final_equity, 2),
            "peak_equity": round(self.peak_equity, 2),
        }


class MetricsCollector:
    """Collects and computes backtest performance metrics."""
    
    def __init__(self, initial_equity: float = 10000.0):
        """Initialize the collector.
        
        Args:
            initial_equity: Starting portfolio equity
        """
        self.initial_equity = initial_equity
        self.equity_curve: list[EquityPoint] = []
        self.trades: list[TradeRecord] = []
        self.returns: list[float] = []
    
    def record_equity(
        self,
        timestamp: int,
        equity: float,
        cash: float,
        exposure: float,
        unrealized_pnl: float,
        realized_pnl: float,
    ) -> None:
        """Record an equity curve point."""
        self.equity_curve.append(EquityPoint(
            timestamp=timestamp,
            equity=equity,
            cash=cash,
            exposure=exposure,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
        ))
        
        # Compute period return
        if len(self.equity_curve) >= 2:
            prev = self.equity_curve[-2].equity
            if prev > 0:
                ret = (equity - prev) / prev
                self.returns.append(ret)
    
    def record_trade(self, trade: TradeRecord) -> None:
        """Record a completed trade."""
        self.trades.append(trade)
    
    def compute_metrics(self) -> BacktestMetrics:
        """Compute all performance metrics.
        
        Returns:
            BacktestMetrics object with computed values
        """
        metrics = BacktestMetrics()
        
        if not self.equity_curve:
            return metrics
        
        # Time range
        metrics.start_timestamp = self.equity_curve[0].timestamp
        metrics.end_timestamp = self.equity_curve[-1].timestamp
        metrics.total_bars = len(self.equity_curve)
        metrics.total_trades = len(self.trades)
        
        # Final equity
        metrics.final_equity = self.equity_curve[-1].equity
        
        # Total return
        if self.initial_equity > 0:
            metrics.total_return = (metrics.final_equity - self.initial_equity) / self.initial_equity
        
        # Annualized return (assuming minute bars)
        duration_years = (metrics.end_timestamp - metrics.start_timestamp) / (365.25 * 24 * 60 * 60 * 1000)
        if duration_years > 0:
            metrics.annual_return = (1 + metrics.total_return) ** (1 / duration_years) - 1
        
        # Returns-based metrics
        if len(self.returns) > 1:
            returns = np.array(self.returns)
            
            # Volatility (annualized)
            metrics.volatility = float(np.std(returns) * np.sqrt(525600))
            
            # Sharpe ratio (assuming 0% risk-free rate)
            if metrics.volatility > 0:
                mean_return = np.mean(returns) * 525600  # Annualized
                metrics.sharpe_ratio = mean_return / metrics.volatility
            
            # Sortino ratio
            downside = returns[returns < 0]
            if len(downside) > 0:
                downside_std = np.std(downside) * np.sqrt(525600)
                if downside_std > 0:
                    mean_return = np.mean(returns) * 525600
                    metrics.sortino_ratio = mean_return / downside_std
        
        # Max drawdown
        equity_values = [p.equity for p in self.equity_curve]
        if equity_values:
            metrics.peak_equity = max(equity_values)
            peak = equity_values[0]
            max_dd = 0.0
            dd_start = 0
            max_dd_duration = 0
            
            for i, eq in enumerate(equity_values):
                if eq > peak:
                    peak = eq
                    dd_start = i
                dd = (peak - eq) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
                    max_dd_duration = i - dd_start
            
            metrics.max_drawdown = max_dd
            if len(self.equity_curve) > 1:
                step_ms = self.equity_curve[1].timestamp - self.equity_curve[0].timestamp
                metrics.max_drawdown_duration_ms = max_dd_duration * step_ms
        
        # Trade statistics
        if self.trades:
            wins = [t for t in self.trades if t.pnl > 0]
            losses = [t for t in self.trades if t.pnl <= 0]
            
            metrics.win_rate = len(wins) / len(self.trades)
            
            if wins:
                metrics.avg_win = sum(t.pnl for t in wins) / len(wins)
            if losses:
                metrics.avg_loss = sum(t.pnl for t in losses) / len(losses)
            
            total_wins = sum(t.pnl for t in wins) if wins else 0
            total_losses = abs(sum(t.pnl for t in losses)) if losses else 0
            if total_losses > 0:
                metrics.profit_factor = total_wins / total_losses
            
            metrics.avg_holding_period_ms = int(
                sum(t.holding_period_ms for t in self.trades) / len(self.trades)
            )
            
            metrics.total_fees = sum(t.fees for t in self.trades)
        
        # Total costs from equity curve
        if self.equity_curve:
            metrics.total_fees = max(
                metrics.total_fees,
                sum(p.realized_pnl for p in self.equity_curve if p.realized_pnl < 0)
            )
        
        return metrics
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert equity curve to DataFrame."""
        if not self.equity_curve:
            return pd.DataFrame()
        
        return pd.DataFrame([
            {
                "timestamp": p.timestamp,
                "equity": p.equity,
                "cash": p.cash,
                "exposure": p.exposure,
                "unrealized_pnl": p.unrealized_pnl,
                "realized_pnl": p.realized_pnl,
            }
            for p in self.equity_curve
        ])
    
    def save_results(self, output_dir: str, run_id: str) -> None:
        """Save backtest results to files.
        
        Args:
            output_dir: Output directory path
            run_id: Unique run identifier
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Save metrics
        metrics = self.compute_metrics()
        with open(f"{output_dir}/{run_id}_metrics.json", "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        
        # Save equity curve
        df = self.to_dataframe()
        if not df.empty:
            df.to_csv(f"{output_dir}/{run_id}_equity.csv", index=False)
        
        # Save trades
        if self.trades:
            trades_df = pd.DataFrame([
                {
                    "entry_timestamp": t.entry_timestamp,
                    "exit_timestamp": t.exit_timestamp,
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "quantity": t.quantity,
                    "pnl": t.pnl,
                    "fees": t.fees,
                    "holding_period_ms": t.holding_period_ms,
                }
                for t in self.trades
            ])
            trades_df.to_csv(f"{output_dir}/{run_id}_trades.csv", index=False)
