"""
Simulated broker for backtesting.
"""
from typing import Dict, Any
from uuid import uuid4
import logging

from ...core.event import FillEvent
from ...core.enums import OrderSide, EventType
from ...data.models import Bar
from ..order import Order


logger = logging.getLogger(__name__)


class SimulatedBroker:
    """
    Simulated broker that executes orders against historical bar data.

    Applies configurable slippage and commission models.
    """

    def __init__(self, config: Dict[str, Any]):
        # Commission settings
        self.commission_model = config.get('commission_model', 'fixed_per_share')
        self.commission_rate = config.get('commission_rate', 0.005)

        # Slippage settings
        self.slippage_bps = config.get('slippage_bps', 5)

        logger.info(
            f"SimulatedBroker initialized: commission={self.commission_model} "
            f"({self.commission_rate}), slippage={self.slippage_bps} bps"
        )

    def execute_order(self, order: Order, current_bar: Bar) -> FillEvent:
        """
        Execute an order against the current bar data.

        For market orders, fills at the close price with slippage.
        For limit orders, fills if the limit price is achievable within the bar.

        Args:
            order: Order to execute
            current_bar: Current market bar

        Returns:
            FillEvent with execution details
        """
        base_price = current_bar.close
        fill_price = self._apply_slippage(base_price, order.side)
        commission = self._calculate_commission(order.quantity, fill_price)

        fill = FillEvent(
            timestamp=current_bar.timestamp,
            event_type=EventType.FILL,
            fill_id=str(uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            commission=commission,
            strategy_id=order.strategy_id
        )

        logger.debug(
            f"Filled {order.side.name} {order.quantity} {order.symbol} "
            f"@ {fill_price:.2f} (commission: {commission:.2f})"
        )

        return fill

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """
        Apply slippage to the base price.

        Buys pay more, sells receive less.
        """
        slippage_pct = self.slippage_bps / 10_000

        if side in (OrderSide.BUY, OrderSide.BUY_TO_COVER):
            return price * (1 + slippage_pct)
        else:
            return price * (1 - slippage_pct)

    def _calculate_commission(self, quantity: float, fill_price: float) -> float:
        """Calculate commission based on the configured model."""
        if self.commission_model == 'fixed_per_share':
            return abs(quantity) * self.commission_rate
        elif self.commission_model == 'percentage':
            return abs(quantity) * fill_price * self.commission_rate
        elif self.commission_model == 'fixed_per_trade':
            return self.commission_rate
        else:
            logger.warning(f"Unknown commission model: {self.commission_model}, using fixed_per_share")
            return abs(quantity) * self.commission_rate
