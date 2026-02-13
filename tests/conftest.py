"""
Shared test fixtures for the trading platform test suite.
"""
import pytest
from datetime import datetime, timedelta

from trading_platform.core.event_bus import EventBus
from trading_platform.core.event import FillEvent, OrderEvent
from trading_platform.core.enums import OrderSide, OrderType, EventType
from trading_platform.portfolio.portfolio import Portfolio
from trading_platform.data.models import Bar


@pytest.fixture
def event_bus():
    """Fresh EventBus in sync mode."""
    return EventBus(mode='sync')


@pytest.fixture
def portfolio(event_bus):
    """Portfolio with known initial capital and a fixed start time."""
    start = datetime(2020, 1, 2)
    return Portfolio(initial_cash=1_000_000, event_bus=event_bus, start_time=start)


@pytest.fixture
def sample_equity_curve():
    """Realistic 4-year equity curve with known values for metric testing."""
    base = datetime(2020, 1, 1)
    # Simulate growth from 1M to ~1.5M over 4 years with some drawdowns
    values = [
        1_000_000, 1_010_000, 1_005_000, 1_020_000, 1_030_000,
        1_015_000, 1_040_000, 1_060_000, 1_050_000, 1_070_000,
        1_080_000, 1_100_000, 1_090_000, 1_110_000, 1_130_000,
        1_120_000, 1_150_000, 1_170_000, 1_160_000, 1_180_000,
        1_200_000, 1_190_000, 1_210_000, 1_230_000, 1_250_000,
        1_240_000, 1_260_000, 1_280_000, 1_300_000, 1_290_000,
        1_310_000, 1_330_000, 1_350_000, 1_340_000, 1_360_000,
        1_380_000, 1_400_000, 1_390_000, 1_410_000, 1_430_000,
        1_450_000, 1_440_000, 1_460_000, 1_480_000, 1_500_000,
    ]
    # Space points roughly monthly over 4 years
    curve = []
    for i, v in enumerate(values):
        t = base + timedelta(days=i * 32)
        curve.append((t, v))
    return curve


@pytest.fixture
def sample_fill_events():
    """List of FillEvents for trade metric testing — 2 round trips with known P&Ls."""
    base = datetime(2020, 3, 1)
    fills = [
        # Round trip 1: Buy 100 AAPL @ 150, sell @ 160 → profit
        FillEvent(
            timestamp=base,
            event_type=EventType.FILL,
            fill_id='f1', order_id='o1', symbol='AAPL',
            side=OrderSide.BUY, quantity=100, fill_price=150.0, commission=1.0,
        ),
        FillEvent(
            timestamp=base + timedelta(days=10),
            event_type=EventType.FILL,
            fill_id='f2', order_id='o2', symbol='AAPL',
            side=OrderSide.SELL, quantity=100, fill_price=160.0, commission=1.0,
        ),
        # Round trip 2: Buy 50 MSFT @ 200, sell @ 190 → loss
        FillEvent(
            timestamp=base + timedelta(days=20),
            event_type=EventType.FILL,
            fill_id='f3', order_id='o3', symbol='MSFT',
            side=OrderSide.BUY, quantity=50, fill_price=200.0, commission=1.0,
        ),
        FillEvent(
            timestamp=base + timedelta(days=35),
            event_type=EventType.FILL,
            fill_id='f4', order_id='o4', symbol='MSFT',
            side=OrderSide.SELL, quantity=50, fill_price=190.0, commission=1.0,
        ),
    ]
    return fills


@pytest.fixture
def sample_bars():
    """Dict of symbol → Bar for execution testing."""
    ts = datetime(2020, 6, 15)
    return {
        'AAPL': Bar(
            timestamp=ts, symbol='AAPL',
            open=150.0, high=155.0, low=149.0, close=153.0, volume=1_000_000,
        ),
        'MSFT': Bar(
            timestamp=ts, symbol='MSFT',
            open=200.0, high=205.0, low=198.0, close=202.0, volume=800_000,
        ),
    }


@pytest.fixture
def risk_config():
    """Standard risk config dict."""
    return {
        'max_position_size': 0.10,
        'max_order_value': 0.10,
        'max_concentration': 0.25,
        'max_leverage': 1.0,
        'max_drawdown': -0.20,
        'max_sector_exposure': 0.35,
        'stop_loss_pct': 0.10,
    }


@pytest.fixture
def sample_order_event():
    """Reusable OrderEvent for testing."""
    return OrderEvent(
        timestamp=datetime(2020, 6, 15),
        event_type=EventType.ORDER,
        order_id='test_order_1',
        symbol='AAPL',
        order_type=OrderType.MARKET,
        side=OrderSide.BUY,
        quantity=100,
    )
