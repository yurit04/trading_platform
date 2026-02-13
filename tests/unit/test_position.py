"""
Unit tests for Position.
"""
import pytest

from trading_platform.portfolio.position import Position


class TestPosition:
    def test_buy_updates_average_price(self):
        pos = Position(symbol='AAPL')
        pos.update(100, 150.0)
        assert pos.quantity == 100
        assert pos.average_price == pytest.approx(150.0)

    def test_sell_calculates_realized_pnl(self):
        pos = Position(symbol='AAPL')
        pos.update(100, 150.0)
        pos.update(-50, 160.0, commission=5.0)
        # PnL = 50 * (160 - 150) - 5 = 495
        assert pos.realized_pnl == pytest.approx(495.0)
        assert pos.quantity == 50

    def test_multiple_buys_average_cost(self):
        pos = Position(symbol='AAPL')
        pos.update(100, 100.0)
        pos.update(100, 200.0)
        # avg = (100*100 + 100*200) / 200 = 150
        assert pos.average_price == pytest.approx(150.0)
        assert pos.quantity == 200

    def test_full_close_resets_average_price(self):
        pos = Position(symbol='AAPL')
        pos.update(100, 150.0)
        pos.update(-100, 160.0)
        assert pos.quantity == 0
        assert pos.average_price == 0.0

    def test_market_value_with_current_price(self):
        pos = Position(symbol='AAPL', quantity=100, average_price=150.0, current_price=160.0)
        assert pos.market_value == pytest.approx(16_000.0)

    def test_market_value_without_current_price(self):
        pos = Position(symbol='AAPL', quantity=100, average_price=150.0)
        # Falls back to average_price
        assert pos.market_value == pytest.approx(15_000.0)

    def test_unrealized_pnl(self):
        pos = Position(symbol='AAPL', quantity=100, average_price=150.0, current_price=160.0)
        assert pos.unrealized_pnl == pytest.approx(1_000.0)

    def test_total_pnl(self):
        pos = Position(symbol='AAPL', quantity=50, average_price=150.0,
                       current_price=160.0, realized_pnl=500.0)
        # unrealized = 50*(160-150) = 500, total = 500 + 500 = 1000
        assert pos.total_pnl == pytest.approx(1_000.0)
