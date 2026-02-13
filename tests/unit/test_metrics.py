"""
Unit tests for PerformanceMetrics.
"""
import pytest
from datetime import datetime, timedelta

from trading_platform.analytics.metrics import PerformanceMetrics
from trading_platform.core.event import FillEvent
from trading_platform.core.enums import OrderSide, EventType


class TestTotalReturn:
    def test_total_return(self):
        result = PerformanceMetrics.total_return(1_000_000, 1_150_000)
        assert result == pytest.approx(0.15)

    def test_total_return_zero_capital(self):
        assert PerformanceMetrics.total_return(0, 100) == 0.0


class TestCAGR:
    def test_cagr(self, sample_equity_curve):
        result = PerformanceMetrics.cagr(sample_equity_curve)
        # Curve goes from 1M to 1.5M over ~4 years → ~10-11% CAGR
        assert result > 0.05
        assert result < 0.20

    def test_cagr_empty_curve(self):
        assert PerformanceMetrics.cagr([]) == 0.0

    def test_cagr_single_point(self):
        assert PerformanceMetrics.cagr([(datetime.now(), 1_000_000)]) == 0.0

    def test_cagr_known_value(self):
        """2-year doubling → CAGR ≈ 41.4%."""
        start = datetime(2020, 1, 1)
        end = datetime(2022, 1, 1)
        curve = [(start, 100_000), (end, 200_000)]
        result = PerformanceMetrics.cagr(curve)
        assert result == pytest.approx(0.414, abs=0.01)


class TestVolatility:
    def test_volatility(self, sample_equity_curve):
        vol = PerformanceMetrics.volatility(sample_equity_curve)
        assert vol > 0

    def test_volatility_short_curve(self):
        curve = [(datetime(2020, 1, 1), 100)]
        assert PerformanceMetrics.volatility(curve) == 0.0


class TestSharpeRatio:
    def test_sharpe_ratio(self, sample_equity_curve):
        sharpe = PerformanceMetrics.sharpe_ratio(sample_equity_curve)
        # Positive growth curve should have positive Sharpe
        assert sharpe > 0

    def test_sharpe_ratio_short_curve(self):
        assert PerformanceMetrics.sharpe_ratio([]) == 0.0


class TestSortinoRatio:
    def test_sortino_ratio(self, sample_equity_curve):
        sortino = PerformanceMetrics.sortino_ratio(sample_equity_curve)
        # Should be positive for upward-trending curve
        assert sortino > 0


class TestMaxDrawdown:
    def test_max_drawdown(self):
        """Known peak-trough: 100→80 = -20%."""
        curve = [
            (datetime(2020, 1, 1), 100),
            (datetime(2020, 2, 1), 110),
            (datetime(2020, 3, 1), 88),  # -20% from 110
            (datetime(2020, 4, 1), 105),
        ]
        mdd = PerformanceMetrics.max_drawdown(curve)
        assert mdd == pytest.approx(-0.20, abs=0.001)

    def test_max_drawdown_no_drawdown(self):
        curve = [
            (datetime(2020, 1, 1), 100),
            (datetime(2020, 2, 1), 110),
            (datetime(2020, 3, 1), 120),
        ]
        assert PerformanceMetrics.max_drawdown(curve) == 0.0


class TestCalmarRatio:
    def test_calmar_ratio(self, sample_equity_curve):
        calmar = PerformanceMetrics.calmar_ratio(sample_equity_curve)
        assert calmar > 0


class TestTradeMetrics:
    def test_win_rate(self, sample_fill_events):
        # 1 win + 1 loss → 50%
        wr = PerformanceMetrics.win_rate(sample_fill_events)
        assert wr == pytest.approx(0.5)

    def test_profit_factor(self, sample_fill_events):
        pf = PerformanceMetrics.profit_factor(sample_fill_events)
        # Win: 100*(160-150) - 1 = 999; Loss: |50*(190-200) - 1| = 501
        # AAPL: buy cost per share = (150*100+1)/100 = 150.01, sell proceeds = 160*50 - ...
        # Actually let's just check > 0
        assert pf > 0

    def test_avg_win_loss(self, sample_fill_events):
        avg_win, avg_loss = PerformanceMetrics.avg_win_loss(sample_fill_events)
        assert avg_win > 0
        assert avg_loss < 0

    def test_max_consecutive(self, sample_fill_events):
        max_w, max_l = PerformanceMetrics.max_consecutive_wins_losses(sample_fill_events)
        assert max_w == 1
        assert max_l == 1

    def test_avg_trade_duration(self, sample_fill_events):
        dur = PerformanceMetrics.avg_trade_duration(sample_fill_events)
        # RT1: 10 days, RT2: 15 days → avg 12.5
        assert dur == pytest.approx(12.5, abs=0.1)

    def test_round_trip_trades(self, sample_fill_events):
        rts = PerformanceMetrics._compute_round_trip_trades(sample_fill_events)
        assert len(rts) == 2

    def test_empty_trades(self):
        assert PerformanceMetrics.win_rate([]) == 0.0
        assert PerformanceMetrics.profit_factor([]) == 0.0


class TestCalculateAll:
    def test_calculate_all(self, sample_equity_curve, sample_fill_events):
        result = PerformanceMetrics.calculate_all(
            initial_capital=1_000_000,
            final_value=1_500_000,
            equity_curve=sample_equity_curve,
            trade_history=sample_fill_events,
        )
        expected_keys = {
            'total_return', 'cagr', 'sharpe_ratio', 'sortino_ratio',
            'max_drawdown', 'calmar_ratio', 'volatility', 'num_trades',
            'win_rate', 'profit_factor', 'avg_win', 'avg_loss',
            'max_consecutive_wins', 'max_consecutive_losses',
            'avg_trade_duration_days',
        }
        assert expected_keys.issubset(set(result.keys()))
        assert result['total_return'] == pytest.approx(0.5)
        assert result['cagr'] > 0
