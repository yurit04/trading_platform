"""
Execution engine for order management and execution.
"""
from typing import Dict, Optional, Any
import logging

from ..core.event_bus import EventBus
from ..core.event import OrderEvent, FillEvent
from ..core.types import OrderId
from ..portfolio.portfolio import Portfolio
from .order import Order


logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Manages order execution and lifecycle.
    
    Routes orders to brokers and handles fill notifications.
    """
    
    def __init__(
        self,
        event_bus: EventBus,
        portfolio: Portfolio,
        mode: str = 'backtest',
        broker: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize execution engine.
        
        Args:
            event_bus: Event bus for communication
            portfolio: Portfolio instance
            mode: 'backtest' or 'live'
            broker: Broker name (for live mode)
            config: Configuration dictionary
        """
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.mode = mode
        self.broker = broker
        self.config = config or {}
        
        self.orders: Dict[OrderId, Order] = {}
        
        # Subscribe to order events
        self.event_bus.subscribe(OrderEvent, self.handle_order_event)
        
        logger.info(f"ExecutionEngine initialized in {mode} mode")
    
    def handle_order_event(self, event: OrderEvent) -> None:
        """
        Handle incoming order events.
        
        Args:
            event: Order event to process
        """
        logger.info(f"Processing order: {event}")
        
        # Create Order object
        order = Order(
            order_id=event.order_id,
            symbol=event.symbol,
            order_type=event.order_type,
            side=event.side,
            quantity=event.quantity,
            limit_price=event.limit_price,
            stop_price=event.stop_price,
            strategy_id=event.strategy_id
        )
        
        self.orders[order.order_id] = order
        
        # Execute order (simplified for now)
        self._execute_order(order)
    
    def _execute_order(self, order: Order) -> None:
        """
        Execute an order.
        
        Args:
            order: Order to execute
        """
        # This is a simplified implementation
        # In reality, this would interface with brokers
        
        logger.info(f"Executing order: {order}")
        
        # For now, just create a fill event
        # Real implementation would handle order routing, partial fills, etc.
