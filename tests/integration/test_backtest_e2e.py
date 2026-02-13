"""
Integration tests for end-to-end backtesting.

Uses CSV data provider with small fixture CSVs to avoid external dependencies.
"""
import pytest
from datetime import datetime
from pathlib import Path

from trading_platform.core.engine import BacktestEngine
from trading_platform.core.event import MarketEvent, OrderEvent, FillEvent
from trading_platform.core.enums import OrderType, OrderSide, EventType
from trading_platform.strategy.base import Strategy


FIXTURES_DIR = str(Path(__file__).parent.parent / 'fixtures' / 'test_data')


class SimpleTestStrategy(Strategy):
    """Minimal strategy that buys on bar 2 and sells on bar 10."""

    def __init__(self, symbols):
        super().__init__(name='SimpleTest')
        self._symbols = symbols
        self._bar_count = {}

    def get_universe(self):
        return self._symbols

    def on_initialize(self):
        pass

    def on_market_event(self, event: MarketEvent):
        symbol = event.symbol
        self._bar_count[symbol] = self._bar_count.get(symbol, 0) + 1
        count = self._bar_count[symbol]

        if count == 2:
            order = OrderEvent(
                timestamp=event.timestamp,
                event_type=EventType.ORDER,
                order_id=f'buy_{symbol}',
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=OrderSide.BUY,
                quantity=10,
            )
            self.submit_order(order)
        elif count == 10:
            pos = self.portfolio.get_position(symbol)
            if pos and pos.quantity > 0:
                order = OrderEvent(
                    timestamp=event.timestamp,
                    event_type=EventType.ORDER,
                    order_id=f'sell_{symbol}',
                    symbol=symbol,
                    order_type=OrderType.MARKET,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                )
                self.submit_order(order)

    def on_fill_event(self, event: FillEvent):
        pass


class TestBacktestE2E:
    def test_backtest_runs_end_to_end(self):
        config = {
            'data': {'provider': 'csv', 'csv_data_dir': FIXTURES_DIR},
        }
        engine = BacktestEngine(
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 12, 31),
            initial_capital=1_000_000,
            config=config,
        )
        engine.add_strategy(SimpleTestStrategy(['AAPL', 'MSFT']))
        engine.initialize()
        results = engine.start()

        assert 'total_return' in results
        assert 'cagr' in results
        assert 'sharpe_ratio' in results
        assert results['initial_capital'] == 1_000_000
        assert results['final_value'] > 0

    def test_backtest_with_risk_limits(self):
        config = {
            'data': {'provider': 'csv', 'csv_data_dir': FIXTURES_DIR},
            'risk': {'max_order_value': 0.0001},  # Very tight limit
        }
        engine = BacktestEngine(
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 12, 31),
            initial_capital=1_000_000,
            config=config,
        )
        engine.add_strategy(SimpleTestStrategy(['AAPL']))
        engine.initialize()
        results = engine.start()

        # With very tight risk limits, orders should be rejected
        assert results['num_trades'] == 0

    def test_cagr_positive_after_fix(self):
        """Verify the CAGR bug fix: equity curve starts at backtest start date."""
        config = {
            'data': {'provider': 'csv', 'csv_data_dir': FIXTURES_DIR},
        }
        engine = BacktestEngine(
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 12, 31),
            initial_capital=1_000_000,
            config=config,
        )
        engine.add_strategy(SimpleTestStrategy(['AAPL']))
        engine.initialize()

        # Verify portfolio equity curve starts at backtest start date
        first_ts = engine.portfolio.equity_curve[0][0]
        assert first_ts.year == 2020

        results = engine.start()
        # CAGR should be a real number (not 0 from the old bug)
        if results['num_trades'] > 0:
            assert results['cagr'] != 0.0

    def test_strategy_generates_trades(self):
        config = {
            'data': {'provider': 'csv', 'csv_data_dir': FIXTURES_DIR},
            'risk': {
                'max_order_value': 0.50,
                'max_position_size': 0.50,
            },
        }
        engine = BacktestEngine(
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 12, 31),
            initial_capital=1_000_000,
            config=config,
        )
        engine.add_strategy(SimpleTestStrategy(['AAPL', 'MSFT']))
        engine.initialize()
        results = engine.start()

        # Strategy buys on bar 2 and sells on bar 10 for each symbol
        assert results['num_trades'] >= 2
