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
    def total_return(initial_capital: float, final_value: float) -> float:
        """Calculate total return as a decimal (e.g. 0.15 = 15%)."""
        if initial_capital == 0:
            return 0.0
        return (final_value - initial_capital) / initial_capital

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
    def win_rate(trade_history: List[FillEvent]) -> float:
        """
        Calculate win rate from trade history.

        Groups trades by symbol, pairs buys with sells to form round-trip
        trades, and calculates the percentage that were profitable.

        Args:
            trade_history: List of FillEvent objects

        Returns:
            Win rate as decimal (e.g. 0.6 = 60%)
        """
        if not trade_history:
            return 0.0

        # Group fills by symbol
        fills_by_symbol: Dict[str, List[FillEvent]] = defaultdict(list)
        for fill in trade_history:
            fills_by_symbol[fill.symbol].append(fill)

        wins = 0
        total_round_trips = 0

        for symbol, fills in fills_by_symbol.items():
            # Track cost basis for open position
            position_qty = 0.0
            position_cost = 0.0

            for fill in fills:
                if fill.side in (OrderSide.BUY, OrderSide.BUY_TO_COVER):
                    position_qty += fill.quantity
                    position_cost += fill.quantity * fill.fill_price + fill.commission
                else:
                    # Closing (partial or full)
                    sell_qty = fill.quantity
                    sell_proceeds = sell_qty * fill.fill_price - fill.commission

                    if position_qty > 0:
                        # Cost basis for the shares being sold
                        avg_cost = position_cost / position_qty
                        cost_basis = avg_cost * sell_qty

                        pnl = sell_proceeds - cost_basis

                        if pnl > 0:
                            wins += 1
                        total_round_trips += 1

                        # Reduce position
                        position_cost -= avg_cost * sell_qty
                        position_qty -= sell_qty

        if total_round_trips == 0:
            return 0.0

        return wins / total_round_trips

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
        return {
            'total_return': PerformanceMetrics.total_return(initial_capital, final_value),
            'sharpe_ratio': PerformanceMetrics.sharpe_ratio(equity_curve),
            'max_drawdown': PerformanceMetrics.max_drawdown(equity_curve),
            'num_trades': len(trade_history),
            'win_rate': PerformanceMetrics.win_rate(trade_history),
        }
