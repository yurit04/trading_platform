"""
Portfolio class for tracking positions and performance.
"""
from typing import Dict, Optional, List
from datetime import datetime
import logging

from ..core.event_bus import EventBus
from ..core.event import FillEvent
from ..core.enums import OrderSide
from ..core.types import Symbol
from .position import Position


logger = logging.getLogger(__name__)


class Portfolio:
    """
    Manages portfolio positions, cash, and performance tracking.
    """

    def __init__(self, initial_cash: float, event_bus: EventBus):
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
        price = event.fill_price
        commission = event.commission

        # Determine signed quantity based on order side
        if event.side in (OrderSide.BUY, OrderSide.BUY_TO_COVER):
            signed_qty = event.quantity
        else:
            signed_qty = -event.quantity

        # Update position
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)

        self.positions[symbol].update(signed_qty, price, commission)

        # Update cash: buying costs money (negative), selling adds money (positive)
        cost = signed_qty * price + commission
        self.cash -= cost

        # Record trade
        self.trade_history.append(event)

        # Update equity curve
        self.equity_curve.append((event.timestamp, self.total_value))

    def update_prices(self, prices: Dict[Symbol, float]) -> None:
        """
        Update current market prices for positions.

        Args:
            prices: Dictionary of symbol to latest price
        """
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price

    def get_position(self, symbol: Symbol) -> Optional[Position]:
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
        """Calculate performance metrics."""
        from ..analytics.metrics import PerformanceMetrics

        return PerformanceMetrics.calculate_all(
            initial_capital=self.initial_cash,
            final_value=self.total_value,
            equity_curve=self.equity_curve,
            trade_history=self.trade_history
        )

    def __repr__(self) -> str:
        return (
            f"Portfolio(cash={self.cash:.2f}, "
            f"positions={len(self.positions)}, "
            f"total_value={self.total_value:.2f})"
        )
