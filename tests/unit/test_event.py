"""
Unit tests for the Event system.
"""
import pytest
from datetime import datetime

from trading_platform.core.event import (
    MarketEvent, SignalEvent, OrderEvent, FillEvent
)
from trading_platform.core.enums import (
    OrderType, OrderSide, OrderStatus, SignalType, AssetClass, EventType
)


class TestMarketEvent:
    """Tests for MarketEvent class."""

    def test_market_event_creation(self):
        """Test creating a market event."""
        event = MarketEvent(
            timestamp=datetime.now(),
            event_type=EventType.MARKET,
            symbol='AAPL',
            open=150.0,
            high=152.0,
            low=149.0,
            close=151.0,
            volume=1000000
        )

        assert event.symbol == 'AAPL'
        assert event.close == 151.0
        assert event.price == 151.0  # price property

    def test_market_event_to_dict(self):
        """Test converting market event to dictionary."""
        event = MarketEvent(
            timestamp=datetime.now(),
            event_type=EventType.MARKET,
            symbol='AAPL',
            open=150.0,
            high=152.0,
            low=149.0,
            close=151.0,
            volume=1000000
        )

        data = event.to_dict()

        assert data['symbol'] == 'AAPL'
        assert data['close'] == 151.0
        assert 'timestamp' in data


class TestSignalEvent:
    """Tests for SignalEvent class."""

    def test_signal_event_creation(self):
        """Test creating a signal event."""
        event = SignalEvent(
            timestamp=datetime.now(),
            event_type=EventType.SIGNAL,
            symbol='AAPL',
            signal_type=SignalType.LONG,
            strength=0.8
        )

        assert event.symbol == 'AAPL'
        assert event.signal_type == SignalType.LONG
        assert event.strength == 0.8

    def test_signal_strength_validation(self):
        """Test that signal strength is validated."""
        with pytest.raises(ValueError):
            SignalEvent(
                timestamp=datetime.now(),
                event_type=EventType.SIGNAL,
                symbol='AAPL',
                signal_type=SignalType.LONG,
                strength=1.5  # Invalid - must be 0-1
            )


class TestOrderEvent:
    """Tests for OrderEvent class."""

    def test_order_event_creation(self):
        """Test creating an order event."""
        event = OrderEvent(
            timestamp=datetime.now(),
            event_type=EventType.ORDER,
            order_id='order_123',
            symbol='AAPL',
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=100
        )

        assert event.order_id == 'order_123'
        assert event.symbol == 'AAPL'
        assert event.order_type == OrderType.MARKET
        assert event.quantity == 100


class TestFillEvent:
    """Tests for FillEvent class."""

    def test_fill_event_creation(self):
        """Test creating a fill event."""
        event = FillEvent(
            timestamp=datetime.now(),
            event_type=EventType.FILL,
            fill_id='fill_123',
            order_id='order_123',
            symbol='AAPL',
            side=OrderSide.BUY,
            quantity=100,
            fill_price=150.0,
            commission=1.0
        )

        assert event.fill_id == 'fill_123'
        assert event.order_id == 'order_123'
        assert event.quantity == 100
        assert event.fill_price == 150.0

    def test_fill_cost_calculation(self):
        """Test cost calculation including commission."""
        event = FillEvent(
            timestamp=datetime.now(),
            event_type=EventType.FILL,
            fill_id='fill_123',
            order_id='order_123',
            symbol='AAPL',
            side=OrderSide.BUY,
            quantity=100,
            fill_price=150.0,
            commission=10.0
        )

        expected_cost = 100 * 150.0 + 10.0
        assert event.cost == expected_cost


if __name__ == '__main__':
    pytest.main([__file__])
