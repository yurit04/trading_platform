"""
Unit tests for RiskManager.
"""
import pytest
from datetime import datetime

from trading_platform.core.event_bus import EventBus
from trading_platform.core.event import OrderEvent, FillEvent
from trading_platform.core.enums import OrderType, OrderSide, EventType
from trading_platform.portfolio.portfolio import Portfolio
from trading_platform.risk.manager import RiskManager


@pytest.fixture
def risk_setup(risk_config):
    """Set up EventBus, Portfolio, and RiskManager for risk tests."""
    eb = EventBus(mode='sync')
    port = Portfolio(initial_cash=1_000_000, event_bus=eb,
                     start_time=datetime(2020, 1, 1))
    rm = RiskManager(eb, port, risk_config)
    return eb, port, rm


def _make_order(symbol='AAPL', side=OrderSide.BUY, quantity=100):
    return OrderEvent(
        timestamp=datetime(2020, 6, 15),
        event_type=EventType.ORDER,
        order_id='test_order',
        symbol=symbol,
        order_type=OrderType.MARKET,
        side=side,
        quantity=quantity,
    )


class TestValidateOrder:
    def test_validate_order_passes(self, risk_setup):
        _, _, rm = risk_setup
        order = _make_order(quantity=10)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is True
        assert reason == ""

    def test_max_order_value_blocks(self, risk_setup):
        _, _, rm = risk_setup
        # 1000 shares * $150 = $150k = 15% of portfolio > 10% limit
        order = _make_order(quantity=1000)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is False
        assert "max_order_value" in reason

    def test_max_position_size_blocks(self, risk_setup):
        eb, port, rm = risk_setup
        # First buy within limits
        fill = FillEvent(
            timestamp=datetime(2020, 6, 14), event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=500, fill_price=150.0, commission=0.0,
        )
        port.handle_fill_event(fill)
        # Now try another buy that would push position > 10%
        order = _make_order(quantity=300)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is False
        assert "max_position_size" in reason

    def test_max_concentration_blocks(self, risk_setup):
        _, _, rm = risk_setup
        rm.max_position_size = 0.30  # raise position limit
        rm.max_order_value = 0.30  # raise order limit
        # 2000 * 150 = 300k = 30% > 25% concentration
        order = _make_order(quantity=2000)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is False
        assert "max_concentration" in reason

    def test_insufficient_cash_blocks(self, risk_setup):
        _, port, rm = risk_setup
        rm.max_order_value = 100.0
        rm.max_position_size = 100.0
        rm.max_concentration = 100.0
        # Try to buy more than available cash: 100000 * 150 = 15M > 1M cash
        order = _make_order(quantity=100_000)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is False
        assert "Insufficient cash" in reason

    def test_drawdown_blocks_buys(self, risk_setup):
        _, port, rm = risk_setup
        # Simulate a drawdown by manipulating equity curve
        port.equity_curve.append((datetime(2020, 6, 1), 750_000))
        order = _make_order(quantity=10)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is False
        assert "drawdown" in reason.lower()

    def test_sells_never_blocked_by_order_value(self, risk_setup):
        eb, port, rm = risk_setup
        # Give portfolio a position to sell
        fill = FillEvent(
            timestamp=datetime(2020, 6, 14), event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=500, fill_price=150.0, commission=0.0,
        )
        port.handle_fill_event(fill)
        # Large sell should pass even if it exceeds max_order_value
        order = _make_order(side=OrderSide.SELL, quantity=500)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is True

    def test_sector_exposure_blocks(self, risk_setup):
        eb, port, rm = risk_setup
        rm.max_sector_exposure = 0.08
        rm.max_order_value = 1.0
        rm.max_position_size = 1.0
        rm.max_concentration = 1.0
        # Buy AAPL (Technology sector) — 100 * 150 = 15k = 1.5%
        order = _make_order(symbol='AAPL', quantity=600)
        passed, reason = rm.validate_order(order, current_price=150.0)
        assert passed is False
        assert "Sector" in reason


class TestPortfolioRisk:
    def test_check_portfolio_risk_alerts(self, risk_setup):
        _, port, rm = risk_setup
        # In normal state, no alerts expected
        alerts = rm.check_portfolio_risk()
        assert isinstance(alerts, list)

    def test_calculate_portfolio_risk_metrics(self, risk_setup):
        _, _, rm = risk_setup
        metrics = rm.calculate_portfolio_risk()
        assert 'var_95' in metrics
        assert 'current_drawdown' in metrics
        assert 'gross_leverage' in metrics
        assert 'num_positions' in metrics
