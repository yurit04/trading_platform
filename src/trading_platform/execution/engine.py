"""
Execution engine for order management and execution.
"""
from typing import Dict, Optional, Any
import logging

from ..core.event_bus import EventBus
from ..core.event import OrderEvent, FillEvent
from ..core.types import OrderId
from ..portfolio.portfolio import Portfolio
from ..data.models import Bar
from .order import Order
from .brokers.simulated_broker import SimulatedBroker


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
        self.broker_name = broker
        self.config = config or {}

        self.orders: Dict[OrderId, Order] = {}
        self.current_bars: Dict[str, Bar] = {}

        # Create broker instance based on mode
        if mode == 'backtest':
            self.broker = SimulatedBroker(self.config)
        else:
            self.broker = None  # Live broker set up separately

        # Subscribe to order events
        self.event_bus.subscribe(OrderEvent, self.handle_order_event)

        logger.info(f"ExecutionEngine initialized in {mode} mode")

    def update_market_data(self, symbol: str, bar: Bar) -> None:
        """
        Update current market data for a symbol.

        Called by the engine on each MarketEvent so the broker
        has access to the current bar when executing orders.

        Args:
            symbol: Symbol to update
            bar: Current bar data
        """
        self.current_bars[symbol] = bar

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
        self._execute_order(order)

    def _execute_order(self, order: Order) -> None:
        """
        Execute an order through the broker.

        Args:
            order: Order to execute
        """
        current_bar = self.current_bars.get(order.symbol)
        if current_bar is None:
            logger.warning(f"No market data for {order.symbol}, rejecting order")
            order.reject("No market data available")
            return

        if self.broker is None:
            logger.error("No broker configured")
            order.reject("No broker configured")
            return

        try:
            fill_event = self.broker.execute_order(order, current_bar)

            # Update order status
            order.update_fill(
                quantity=fill_event.quantity,
                price=fill_event.fill_price,
                commission=fill_event.commission
            )

            # Publish fill event to event bus
            self.event_bus.publish(fill_event)

            logger.info(
                f"Order filled: {order.symbol} {order.side.name} "
                f"{order.quantity} @ {fill_event.fill_price:.2f}"
            )

        except Exception as e:
            logger.error(f"Order execution failed: {e}", exc_info=True)
            order.reject(str(e))
