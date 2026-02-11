"""
Position class for tracking individual holdings.
"""
from dataclasses import dataclass
from typing import Optional

from ..core.types import Symbol, Price, Quantity


@dataclass
class Position:
    """
    Represents a position in a security.
    """
    symbol: Symbol
    quantity: Quantity = 0
    average_price: Price = 0.0
    current_price: Optional[Price] = None
    realized_pnl: float = 0.0
    
    def update(self, quantity: Quantity, price: Price, commission: float = 0.0) -> None:
        """
        Update position with a trade.
        
        Args:
            quantity: Quantity traded (positive for buy, negative for sell)
            price: Trade price
            commission: Commission paid
        """
        if quantity > 0:  # Buy
            total_cost = (self.quantity * self.average_price) + (quantity * price)
            self.quantity += quantity
            self.average_price = total_cost / self.quantity if self.quantity > 0 else 0
        else:  # Sell
            pnl = abs(quantity) * (price - self.average_price) - commission
            self.realized_pnl += pnl
            self.quantity += quantity  # quantity is negative
            
            if self.quantity == 0:
                self.average_price = 0.0
    
    @property
    def market_value(self) -> float:
        """Calculate current market value."""
        if self.current_price is None:
            return self.quantity * self.average_price
        return self.quantity * self.current_price
    
    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L."""
        if self.current_price is None:
            return 0.0
        return self.quantity * (self.current_price - self.average_price)
    
    @property
    def total_pnl(self) -> float:
        """Calculate total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl
    
    def __repr__(self) -> str:
        return (
            f"Position(symbol={self.symbol}, "
            f"quantity={self.quantity}, "
            f"avg_price={self.average_price:.2f}, "
            f"value={self.market_value:.2f})"
        )
