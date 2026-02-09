"""
Portfolio class for tracking positions and performance.
"""
from typing import Dict, Optional, List
from datetime import datetime
import logging

from ..core.event_bus import EventBus
from ..core.event import FillEvent
from ..core.types import Symbol
from .position import Position


logger = logging.getLogger(__name__)


class Portfolio:
    """
    Manages portfolio positions, cash, and performance tracking.
    """
    
    def __init__(self, initial_cash: float, event_bus: EventBus):
        """
        Initialize portfolio.
        
        Args:
            initial_cash: Starting cash balance
            event_bus: Event bus for communication
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.event_bus = event_bus
        
        self.positions: Dict[Symbol, Position] = {}
        self.trade_history: List[FillEvent] = []
        
        # Performance tracking
        self.equity_curve: List[tuple] = [(datetime.now(), initial_cash)]
        
        # Subscribe to fill events
        self.event_bus.subscribe(FillEvent, self.handle_fill_event)
        
        logger.info(f"Portfolio initialized with cash={initial_cash}")
    
    def handle_fill_event(self, event: FillEvent) -> None:
        """
        Handle order fill events.
        
        Args:
            event: Fill event
        """
        logger.info(f"Processing fill: {event}")
        
        symbol = event.symbol
        quantity = event.quantity
        price = event.fill_price
        commission = event.commission
        
        # Update position
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)
        
        self.positions[symbol].update(quantity, price, commission)
        
        # Update cash
        cost = quantity * price + commission
        self.cash -= cost
        
        # Record trade
        self.trade_history.append(event)
        
        # Update equity curve
        self.equity_curve.append((event.timestamp, self.total_value))
    
    def get_position(self, symbol: Symbol) -> Optional[Position]:
        """
        Get position for a symbol.
        
        Args:
            symbol: Symbol to query
            
        Returns:
            Position or None
        """
        return self.positions.get(symbol)
    
    @property
    def total_value(self) -> float:
        """Calculate total portfolio value."""
        positions_value = sum(pos.market_value for pos in self.positions.values())
        return self.cash + positions_value
    
    @property
    def positions_value(self) -> float:
        """Calculate total positions value."""
        return sum(pos.market_value for pos in self.positions.values())
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """
        Calculate performance metrics.
        
        Returns:
            Dictionary of metrics
        """
        total_return = (self.total_value - self.initial_cash) / self.initial_cash
        
        return {
            'total_return': total_return,
            'num_trades': len(self.trade_history),
            'sharpe_ratio': 0.0,  # Placeholder
            'max_drawdown': 0.0,  # Placeholder
            'win_rate': 0.0,  # Placeholder
        }
    
    def __repr__(self) -> str:
        return (
            f"Portfolio(cash={self.cash:.2f}, "
            f"positions={len(self.positions)}, "
            f"total_value={self.total_value:.2f})"
        )
