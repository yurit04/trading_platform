"""
Unit tests for ExecutionEngine and SimulatedBroker.
"""
import pytest
from datetime import datetime

from trading_platform.core.event_bus import EventBus
from trading_platform.core.event import OrderEvent, FillEvent
from trading_platform.core.enums import OrderType, OrderSide, EventType
from trading_platform.portfolio.portfolio import Portfolio
from trading_platform.execution.engine import ExecutionEngine
from trading_platform.execution.brokers.simulated_broker import SimulatedBroker
from trading_platform.execution.order import Order
from trading_platform.risk.manager import RiskManager
from trading_platform.data.models import Bar


@pytest.fixture
def exec_setup():
    """Set up EventBus, Portfolio, RiskManager, and ExecutionEngine."""
    eb = EventBus(mode='sync')
    port = Portfolio(initial_cash=1_000_000, event_bus=eb,
                     start_time=datetime(2020, 1, 1))
    rm = RiskManager(eb, port, {})
    ee = ExecutionEngine(eb, port, mode='backtest', config={}, risk_manager=rm)
    return eb, port, rm, ee


def _make_bar(symbol='AAPL', close=150.0):
    open_ = close - 2.0
    high = close + 5.0
    low = open_ - 1.0
    return Bar(
        timestamp=datetime(2020, 6, 15), symbol=symbol,
        open=open_, high=high, low=low, close=close, volume=1_000_000,
    )


class TestSimulatedBroker:
    def test_market_order_fills_at_close_with_slippage(self):
        broker = SimulatedBroker({'slippage_bps': 10, 'commission_model': 'fixed_per_share',
                                  'commission_rate': 0.005})
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        bar = _make_bar(close=150.0)

        fill = broker.execute_order(order, bar)
        # Buy slippage: 150 * (1 + 10/10000) = 150.15
        assert fill.fill_price == pytest.approx(150.15)
        assert fill.quantity == 100

    def test_commission_per_share(self):
        broker = SimulatedBroker({'commission_model': 'fixed_per_share',
                                  'commission_rate': 0.01})
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=200)
        fill = broker.execute_order(order, _make_bar())
        assert fill.commission == pytest.approx(200 * 0.01)

    def test_commission_percentage(self):
        broker = SimulatedBroker({'commission_model': 'percentage',
                                  'commission_rate': 0.001})
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=100)
        fill = broker.execute_order(order, _make_bar(close=100.0))
        # commission = 100 * fill_price * 0.001
        expected = 100 * fill.fill_price * 0.001
        assert fill.commission == pytest.approx(expected)

    def test_commission_per_trade(self):
        broker = SimulatedBroker({'commission_model': 'fixed_per_trade',
                                  'commission_rate': 9.99})
        order = Order(symbol='AAPL', order_type=OrderType.MARKET,
                      side=OrderSide.BUY, quantity=500)
        fill = broker.execute_order(order, _make_bar())
        assert fill.commission == pytest.approx(9.99)


class TestExecutionEngine:
    def test_handles_order_end_to_end(self, exec_setup):
        eb, port, rm, ee = exec_setup
        bar = _make_bar()
        ee.update_market_data('AAPL', bar)

        order_event = OrderEvent(
            timestamp=datetime(2020, 6, 15), event_type=EventType.ORDER,
            order_id='o1', symbol='AAPL', order_type=OrderType.MARKET,
            side=OrderSide.BUY, quantity=10,
        )
        ee.handle_order_event(order_event)

        # Portfolio should have AAPL position
        assert 'AAPL' in port.positions
        assert port.positions['AAPL'].quantity == 10

    def test_rejects_no_market_data(self, exec_setup):
        eb, port, rm, ee = exec_setup
        order_event = OrderEvent(
            timestamp=datetime(2020, 6, 15), event_type=EventType.ORDER,
            order_id='o1', symbol='XYZ', order_type=OrderType.MARKET,
            side=OrderSide.BUY, quantity=10,
        )
        ee.handle_order_event(order_event)
        # Order should be rejected, no position created
        assert 'XYZ' not in port.positions

    def test_risk_rejection(self, exec_setup):
        eb, port, rm, ee = exec_setup
        bar = _make_bar(close=150.0)
        ee.update_market_data('AAPL', bar)

        # Order exceeds max_order_value (10%)
        order_event = OrderEvent(
            timestamp=datetime(2020, 6, 15), event_type=EventType.ORDER,
            order_id='o1', symbol='AAPL', order_type=OrderType.MARKET,
            side=OrderSide.BUY, quantity=1000,
        )
        ee.handle_order_event(order_event)

        # Should be rejected — no position
        pos = port.get_position('AAPL')
        assert pos is None or pos.quantity == 0

    def test_publishes_fill(self, exec_setup):
        eb, port, rm, ee = exec_setup
        bar = _make_bar()
        ee.update_market_data('AAPL', bar)

        fills = []
        eb.subscribe(FillEvent, lambda e: fills.append(e))

        order_event = OrderEvent(
            timestamp=datetime(2020, 6, 15), event_type=EventType.ORDER,
            order_id='o1', symbol='AAPL', order_type=OrderType.MARKET,
            side=OrderSide.BUY, quantity=10,
        )
        ee.handle_order_event(order_event)

        assert len(fills) == 1
        assert fills[0].symbol == 'AAPL'
        assert fills[0].quantity == 10
