"""
Performance metrics for portfolio analysis.
"""
from typing import List, Dict, Tuple
from datetime import datetime
from collections import defaultdict
import logging

import numpy as np
import pandas as pd

from ..core.event import FillEvent
from ..core.enums import OrderSide


logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """Calculate portfolio performance metrics from equity curve and trade history."""

    @staticmethod
    def daily_returns(equity_curve: List[Tuple[datetime, float]]) -> pd.Series:
        """
        Convert equity curve to daily returns with DatetimeIndex.

        Args:
            equity_curve: List of (timestamp, portfolio_value) tuples

        Returns:
            pd.Series of daily returns with DatetimeIndex
        """
        if len(equity_curve) < 2:
            return pd.Series(dtype=float)

        timestamps = [t for t, _ in equity_curve]
        values = [v for _, v in equity_curve]
        series = pd.Series(values, index=pd.DatetimeIndex(timestamps))

        # Resample to daily (take last value per day) then compute returns
        daily = series.resample('D').last().dropna()
        returns = daily.pct_change().dropna()
        return returns

    @staticmethod
    def total_return(initial_capital: float, final_value: float) -> float:
        """Calculate total return as a decimal (e.g. 0.15 = 15%)."""
        if initial_capital == 0:
            return 0.0
        return (final_value - initial_capital) / initial_capital

    @staticmethod
    def cagr(equity_curve: List[Tuple[datetime, float]]) -> float:
        """Calculate compound annual growth rate."""
        if len(equity_curve) < 2:
            return 0.0

        start_val = equity_curve[0][1]
        end_val = equity_curve[-1][1]
        start_date = equity_curve[0][0]
        end_date = equity_curve[-1][0]

        if start_val <= 0:
            return 0.0

        years = (end_date - start_date).days / 365.25
        if years <= 0:
            return 0.0

        return (end_val / start_val) ** (1 / years) - 1

    @staticmethod
    def volatility(
        equity_curve: List[Tuple[datetime, float]],
        periods_per_year: int = 252
    ) -> float:
        """Calculate annualized daily return volatility."""
        if len(equity_curve) < 3:
            return 0.0

        values = pd.Series([v for _, v in equity_curve])
        returns = values.pct_change().dropna()

        if len(returns) == 0:
            return 0.0

        return float(returns.std() * np.sqrt(periods_per_year))

    @staticmethod
    def sharpe_ratio(
        equity_curve: List[Tuple[datetime, float]],
        risk_free_rate: float = 0.02,
        periods_per_year: int = 252
    ) -> float:
        """
        Calculate annualized Sharpe ratio from equity curve.

        Args:
            equity_curve: List of (timestamp, portfolio_value) tuples
            risk_free_rate: Annual risk-free rate
            periods_per_year: Trading periods per year (252 for daily)

        Returns:
            Annualized Sharpe ratio
        """
        if len(equity_curve) < 3:
            return 0.0

        values = pd.Series([v for _, v in equity_curve])
        returns = values.pct_change().dropna()

        if returns.std() == 0 or len(returns) == 0:
            return 0.0

        daily_rf = risk_free_rate / periods_per_year
        excess_returns = returns - daily_rf

        return float(np.sqrt(periods_per_year) * excess_returns.mean() / excess_returns.std())

    @staticmethod
    def sortino_ratio(
        equity_curve: List[Tuple[datetime, float]],
        risk_free_rate: float = 0.02,
        periods_per_year: int = 252
    ) -> float:
        """Calculate annualized Sortino ratio (downside deviation variant)."""
        if len(equity_curve) < 3:
            return 0.0

        values = pd.Series([v for _, v in equity_curve])
        returns = values.pct_change().dropna()

        if len(returns) == 0:
            return 0.0

        daily_rf = risk_free_rate / periods_per_year
        excess_returns = returns - daily_rf

        downside = returns[returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0

        downside_std = downside.std()
        return float(np.sqrt(periods_per_year) * excess_returns.mean() / downside_std)

    @staticmethod
    def max_drawdown(equity_curve: List[Tuple[datetime, float]]) -> float:
        """
        Calculate maximum drawdown as a negative decimal (e.g. -0.15 = -15%).

        Args:
            equity_curve: List of (timestamp, portfolio_value) tuples

        Returns:
            Maximum drawdown (negative value)
        """
        if len(equity_curve) < 2:
            return 0.0

        values = pd.Series([v for _, v in equity_curve])
        running_max = values.expanding().max()
        drawdown = (values - running_max) / running_max

        return float(drawdown.min())

    @staticmethod
    def calmar_ratio(equity_curve: List[Tuple[datetime, float]]) -> float:
        """Calculate Calmar ratio (CAGR / abs(max drawdown))."""
        c = PerformanceMetrics.cagr(equity_curve)
        mdd = PerformanceMetrics.max_drawdown(equity_curve)

        if mdd == 0:
            return 0.0

        return c / abs(mdd)

    @staticmethod
    def drawdown_series(equity_curve: List[Tuple[datetime, float]]) -> pd.Series:
        """Return drawdown series with DatetimeIndex for charting."""
        if len(equity_curve) < 2:
            return pd.Series(dtype=float)

        timestamps = [t for t, _ in equity_curve]
        values = pd.Series([v for _, v in equity_curve], index=pd.DatetimeIndex(timestamps))
        running_max = values.expanding().max()
        return (values - running_max) / running_max

    @staticmethod
    def _compute_round_trip_trades(
        trade_history: List[FillEvent]
    ) -> List[Dict]:
        """
        Compute round-trip trades from fill history.

        Returns list of dicts with keys: symbol, pnl, entry_time, exit_time, side
        """
        if not trade_history:
            return []

        fills_by_symbol: Dict[str, List[FillEvent]] = defaultdict(list)
        for fill in trade_history:
            fills_by_symbol[fill.symbol].append(fill)

        round_trips = []

        for symbol, fills in fills_by_symbol.items():
            position_qty = 0.0
            position_cost = 0.0
            entry_time = None

            for fill in fills:
                if fill.side in (OrderSide.BUY, OrderSide.BUY_TO_COVER):
                    if position_qty == 0:
                        entry_time = fill.timestamp
                    position_qty += fill.quantity
                    position_cost += fill.quantity * fill.fill_price + fill.commission
                else:
                    sell_qty = fill.quantity
                    sell_proceeds = sell_qty * fill.fill_price - fill.commission

                    if position_qty > 0:
                        avg_cost = position_cost / position_qty
                        cost_basis = avg_cost * sell_qty
                        pnl = sell_proceeds - cost_basis

                        round_trips.append({
                            'symbol': symbol,
                            'pnl': pnl,
                            'entry_time': entry_time,
                            'exit_time': fill.timestamp,
                        })

                        position_cost -= avg_cost * sell_qty
                        position_qty -= sell_qty

                        if position_qty == 0:
                            entry_time = None

        return round_trips

    @staticmethod
    def win_rate(trade_history: List[FillEvent]) -> float:
        """Calculate win rate from trade history."""
        round_trips = PerformanceMetrics._compute_round_trip_trades(trade_history)
        if not round_trips:
            return 0.0

        wins = sum(1 for rt in round_trips if rt['pnl'] > 0)
        return wins / len(round_trips)

    @staticmethod
    def profit_factor(trade_history: List[FillEvent]) -> float:
        """Calculate profit factor (gross profits / gross losses)."""
        round_trips = PerformanceMetrics._compute_round_trip_trades(trade_history)
        if not round_trips:
            return 0.0

        gross_profit = sum(rt['pnl'] for rt in round_trips if rt['pnl'] > 0)
        gross_loss = abs(sum(rt['pnl'] for rt in round_trips if rt['pnl'] < 0))

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    @staticmethod
    def avg_win_loss(trade_history: List[FillEvent]) -> Tuple[float, float]:
        """Calculate average winning and losing trade P&L."""
        round_trips = PerformanceMetrics._compute_round_trip_trades(trade_history)
        if not round_trips:
            return 0.0, 0.0

        wins = [rt['pnl'] for rt in round_trips if rt['pnl'] > 0]
        losses = [rt['pnl'] for rt in round_trips if rt['pnl'] < 0]

        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        return avg_win, avg_loss

    @staticmethod
    def max_consecutive_wins_losses(trade_history: List[FillEvent]) -> Tuple[int, int]:
        """Calculate max consecutive wins and losses."""
        round_trips = PerformanceMetrics._compute_round_trip_trades(trade_history)
        if not round_trips:
            return 0, 0

        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for rt in round_trips:
            if rt['pnl'] > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif rt['pnl'] < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        return max_wins, max_losses

    @staticmethod
    def avg_trade_duration(trade_history: List[FillEvent]) -> float:
        """Calculate average trade duration in days."""
        round_trips = PerformanceMetrics._compute_round_trip_trades(trade_history)
        if not round_trips:
            return 0.0

        durations = []
        for rt in round_trips:
            if rt['entry_time'] and rt['exit_time']:
                duration = (rt['exit_time'] - rt['entry_time']).total_seconds() / 86400
                durations.append(duration)

        if not durations:
            return 0.0

        return sum(durations) / len(durations)

    @staticmethod
    def calculate_all(
        initial_capital: float,
        final_value: float,
        equity_curve: List[Tuple[datetime, float]],
        trade_history: List[FillEvent]
    ) -> Dict[str, float]:
        """
        Calculate all performance metrics.

        Args:
            initial_capital: Starting capital
            final_value: Ending portfolio value
            equity_curve: List of (timestamp, value) tuples
            trade_history: List of FillEvent objects

        Returns:
            Dictionary of metric name to value
        """
        avg_win, avg_loss = PerformanceMetrics.avg_win_loss(trade_history)
        max_cons_wins, max_cons_losses = PerformanceMetrics.max_consecutive_wins_losses(trade_history)

        return {
            'total_return': PerformanceMetrics.total_return(initial_capital, final_value),
            'cagr': PerformanceMetrics.cagr(equity_curve),
            'sharpe_ratio': PerformanceMetrics.sharpe_ratio(equity_curve),
            'sortino_ratio': PerformanceMetrics.sortino_ratio(equity_curve),
            'max_drawdown': PerformanceMetrics.max_drawdown(equity_curve),
            'calmar_ratio': PerformanceMetrics.calmar_ratio(equity_curve),
            'volatility': PerformanceMetrics.volatility(equity_curve),
            'num_trades': len(trade_history),
            'win_rate': PerformanceMetrics.win_rate(trade_history),
            'profit_factor': PerformanceMetrics.profit_factor(trade_history),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_consecutive_wins': max_cons_wins,
            'max_consecutive_losses': max_cons_losses,
            'avg_trade_duration_days': PerformanceMetrics.avg_trade_duration(trade_history),
        }
