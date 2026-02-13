"""
Unit tests for Order.
"""
import pytest

from trading_platform.execution.order import Order
from trading_platform.core.enums import OrderType, OrderSide, OrderStatus


class TestOrder:
    def test_order_creation(self):
        order = Order(
            symbol='AAPL', order_type=OrderType.MARKET,
            side=OrderSide.BUY, quantity=100,
        )
        assert order.symbol == 'AAPL'
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0

    def test_order_validation_positive_quantity(self):
        with pytest.raises(ValueError, match="positive"):
            Order(symbol='AAPL', order_type=OrderType.MARKET,
                  side=OrderSide.BUY, quantity=-10)

    def test_limit_order_requires_price(self):
        with pytest.raises(ValueError, match="Limit price"):
            Order(symbol='AAPL', order_type=OrderType.LIMIT,
                  side=OrderSide.BUY, quantity=100)

    def test_update_fill(self):
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        order.update_fill(100, 150.0, commission=5.0)
        assert order.status == OrderStatus.FILLED
        assert order.average_fill_price == pytest.approx(150.0)
        assert order.commission == pytest.approx(5.0)

    def test_update_fill_partial(self):
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        order.update_fill(60, 150.0)
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.remaining_quantity == 40

        order.update_fill(40, 155.0)
        assert order.status == OrderStatus.FILLED
        # avg = (60*150 + 40*155) / 100 = 152
        assert order.average_fill_price == pytest.approx(152.0)

    def test_fill_exceeds_quantity_raises(self):
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        with pytest.raises(ValueError, match="exceeds"):
            order.update_fill(150, 150.0)

    def test_cancel_order(self):
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        order.cancel()
        assert order.status == OrderStatus.CANCELLED
        # Can't cancel again
        with pytest.raises(ValueError):
            order.cancel()

    def test_reject_order(self):
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        order.reject(reason="Risk limit breached")
        assert order.status == OrderStatus.REJECTED
        assert order.notes == "Risk limit breached"
