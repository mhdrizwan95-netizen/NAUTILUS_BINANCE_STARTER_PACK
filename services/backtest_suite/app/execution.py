"""Execution model with fees and slippage simulation."""

from dataclasses import dataclass, field
from typing import Literal

from .config import settings


@dataclass
class Fill:
    """Simulated order fill."""
    timestamp: int
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float
    quantity: float
    fee: float
    slippage: float
    
    @property
    def notional(self) -> float:
        """Gross notional value."""
        return self.price * self.quantity
    
    @property
    def net_cost(self) -> float:
        """Net cost including fees and slippage."""
        base = self.notional
        if self.side == "BUY":
            return base + self.fee + self.slippage
        return base - self.fee - self.slippage


@dataclass
class Position:
    """Simulated position."""
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    def is_open(self) -> bool:
        return abs(self.quantity) > 1e-9


@dataclass
class Portfolio:
    """Simulated portfolio state."""
    cash: float = 10000.0
    positions: dict[str, Position] = field(default_factory=dict)
    total_fees: float = 0.0
    total_slippage: float = 0.0
    trade_count: int = 0
    
    @property
    def equity(self) -> float:
        """Total equity (cash + unrealized PnL)."""
        return self.cash + sum(p.unrealized_pnl for p in self.positions.values())
    
    @property
    def exposure(self) -> float:
        """Total exposure (sum of absolute position values)."""
        return sum(
            abs(p.quantity) * p.avg_entry_price
            for p in self.positions.values()
            if p.is_open()
        )


class ExecutionModel:
    """Simulates order execution with realistic costs.
    
    Implements a simple cost model with:
    - Fixed fee as basis points
    - Slippage proportional to volatility
    """
    
    def __init__(
        self,
        cost_bps: float = None,
        slippage_bps_per_vol: float = None,
    ):
        self.cost_bps = cost_bps or settings.COST_BPS
        self.slippage_bps_per_vol = slippage_bps_per_vol or settings.SLIPPAGE_BPS_PER_VOL
    
    def execute(
        self,
        portfolio: Portfolio,
        timestamp: int,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: float,
        price: float,
        volatility: float = 0.02,
    ) -> Fill | None:
        """Execute a simulated order.
        
        Args:
            portfolio: Current portfolio state
            timestamp: Order timestamp
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity
            price: Reference price (mid)
            volatility: Recent volatility for slippage calculation
            
        Returns:
            Fill object if executed, None otherwise
        """
        if quantity <= 0:
            return None
        
        # Calculate costs
        notional = price * quantity
        fee = notional * (self.cost_bps / 10000)
        slippage_bps = self.slippage_bps_per_vol * volatility * 100
        slippage = notional * (slippage_bps / 10000)
        
        # Adjust execution price for slippage
        if side == "BUY":
            exec_price = price * (1 + slippage_bps / 10000)
        else:
            exec_price = price * (1 - slippage_bps / 10000)
        
        # Check cash for buys
        total_cost = notional + fee + slippage
        if side == "BUY" and total_cost > portfolio.cash:
            # Adjust quantity to available cash
            max_notional = portfolio.cash / (1 + (self.cost_bps + slippage_bps) / 10000)
            quantity = max_notional / price
            if quantity <= 0:
                return None
            notional = price * quantity
            fee = notional * (self.cost_bps / 10000)
            slippage = notional * (slippage_bps / 10000)
        
        # Create fill
        fill = Fill(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            price=exec_price,
            quantity=quantity,
            fee=fee,
            slippage=slippage,
        )
        
        # Update portfolio
        self._apply_fill(portfolio, fill)
        
        return fill
    
    def _apply_fill(self, portfolio: Portfolio, fill: Fill) -> None:
        """Apply a fill to the portfolio."""
        symbol = fill.symbol
        
        # Get or create position
        if symbol not in portfolio.positions:
            portfolio.positions[symbol] = Position(symbol=symbol)
        pos = portfolio.positions[symbol]
        
        # Update position
        if fill.side == "BUY":
            # Opening or adding to long
            old_value = pos.quantity * pos.avg_entry_price
            new_value = fill.quantity * fill.price
            pos.quantity += fill.quantity
            if pos.quantity > 0:
                pos.avg_entry_price = (old_value + new_value) / pos.quantity
            portfolio.cash -= fill.net_cost
        else:
            # Closing or adding to short
            if pos.quantity > 0:
                # Closing long position
                realized = (fill.price - pos.avg_entry_price) * fill.quantity
                pos.realized_pnl += realized
                pos.quantity -= fill.quantity
                portfolio.cash += fill.notional - fill.fee - fill.slippage + realized
            else:
                # Opening short (simplified)
                pos.quantity -= fill.quantity
                pos.avg_entry_price = fill.price
                portfolio.cash += fill.notional - fill.fee - fill.slippage
        
        # Update totals
        portfolio.total_fees += fill.fee
        portfolio.total_slippage += fill.slippage
        portfolio.trade_count += 1
    
    def mark_to_market(self, portfolio: Portfolio, prices: dict[str, float]) -> None:
        """Update unrealized PnL with current prices."""
        for symbol, pos in portfolio.positions.items():
            if symbol in prices and pos.is_open():
                current_price = prices[symbol]
                pos.unrealized_pnl = (current_price - pos.avg_entry_price) * pos.quantity
