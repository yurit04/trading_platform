"""
Unit tests for Portfolio.
"""
import pytest
from datetime import datetime

from trading_platform.core.event_bus import EventBus
from trading_platform.core.event import FillEvent
from trading_platform.core.enums import OrderSide, EventType
from trading_platform.portfolio.portfolio import Portfolio


class TestPortfolio:
    def test_initial_state(self, portfolio):
        assert portfolio.cash == 1_000_000
        assert portfolio.total_value == pytest.approx(1_000_000)
        assert len(portfolio.positions) == 0
        assert len(portfolio.equity_curve) == 1

    def test_handle_buy_fill(self, portfolio):
        fill = FillEvent(
            timestamp=datetime(2020, 1, 5),
            event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=100, fill_price=150.0, commission=5.0,
        )
        portfolio.handle_fill_event(fill)

        assert portfolio.cash == pytest.approx(1_000_000 - (100 * 150.0 + 5.0))
        assert 'AAPL' in portfolio.positions
        assert portfolio.positions['AAPL'].quantity == 100

    def test_handle_sell_fill(self, portfolio):
        # First buy
        buy = FillEvent(
            timestamp=datetime(2020, 1, 5),
            event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=100, fill_price=150.0, commission=0.0,
        )
        portfolio.handle_fill_event(buy)

        # Then sell
        sell = FillEvent(
            timestamp=datetime(2020, 1, 10),
            event_type=EventType.FILL,
            fill_id='f2', order_id='o2', symbol='AAPL',
            side=OrderSide.SELL, quantity=50, fill_price=160.0, commission=0.0,
        )
        portfolio.handle_fill_event(sell)

        assert portfolio.positions['AAPL'].quantity == 50
        # Cash = 1M - 15000 + 8000 = 993000
        assert portfolio.cash == pytest.approx(993_000.0)

    def test_equity_curve_updates(self, portfolio):
        fill = FillEvent(
            timestamp=datetime(2020, 1, 5),
            event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=100, fill_price=150.0, commission=0.0,
        )
        portfolio.handle_fill_event(fill)
        # Initial + 1 fill = 2 entries
        assert len(portfolio.equity_curve) == 2

    def test_total_value_with_positions(self, portfolio):
        fill = FillEvent(
            timestamp=datetime(2020, 1, 5),
            event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=100, fill_price=150.0, commission=0.0,
        )
        portfolio.handle_fill_event(fill)
        portfolio.update_prices({'AAPL': 160.0})

        # Cash = 1M - 15000 = 985000, positions = 100*160 = 16000
        assert portfolio.total_value == pytest.approx(1_001_000.0)

    def test_update_prices(self, portfolio):
        fill = FillEvent(
            timestamp=datetime(2020, 1, 5),
            event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=100, fill_price=150.0, commission=0.0,
        )
        portfolio.handle_fill_event(fill)
        portfolio.update_prices({'AAPL': 200.0})
        assert portfolio.positions['AAPL'].current_price == 200.0

    def test_multiple_symbols(self, portfolio):
        for symbol, price in [('AAPL', 150.0), ('MSFT', 200.0)]:
            fill = FillEvent(
                timestamp=datetime(2020, 1, 5),
                event_type=EventType.FILL,
                fill_id=f'f_{symbol}', order_id=f'o_{symbol}', symbol=symbol,
                side=OrderSide.BUY, quantity=50, fill_price=price, commission=0.0,
            )
            portfolio.handle_fill_event(fill)
        assert len(portfolio.positions) == 2

    def test_performance_metrics_returns_dict(self, portfolio):
        metrics = portfolio.get_performance_metrics()
        assert isinstance(metrics, dict)
        assert 'total_return' in metrics
