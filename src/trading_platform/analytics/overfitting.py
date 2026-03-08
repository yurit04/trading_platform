"""
Overfitting detection tools for backtest analysis.

Currently implements a return permutation test: shuffles the strategy's
daily return series N times and computes the null distribution of a
performance metric (default: Sharpe ratio). The p-value measures how
often a random ordering achieves an equal or better result.
"""
from typing import List, Tuple, Dict, Optional
from datetime import datetime
import logging

import numpy as np
import pandas as pd

from .metrics import PerformanceMetrics


logger = logging.getLogger(__name__)


class PermutationTest:
    """
    Return permutation test for strategy overfitting detection.

    Null hypothesis: the strategy's performance metric is no better than
    what would be achieved by randomly reordering the same daily returns.

    Limitations:
    - Does not re-run the backtest engine; only shuffles the equity curve.
    - Assumes approximately i.i.d. returns. Strategies with strong serial
      correlation (e.g. momentum) may see inflated p-values.
    - Does not account for data-mining bias from parameter search.
    """

    SUPPORTED_METRICS = ('sharpe_ratio', 'sortino_ratio', 'calmar_ratio', 'total_return')

    def __init__(
        self,
        equity_curve: List[Tuple[datetime, float]],
        n_permutations: int = 1000,
        metric: str = 'sharpe_ratio',
        risk_free_rate: float = 0.02,
        random_seed: Optional[int] = None,
    ):
        """
        Args:
            equity_curve: List of (timestamp, portfolio_value) tuples from a backtest.
            n_permutations: Number of random shuffles to generate the null distribution.
            metric: Performance metric to test. One of: sharpe_ratio, sortino_ratio,
                    calmar_ratio, total_return.
            risk_free_rate: Annual risk-free rate used for Sharpe/Sortino calculations.
            random_seed: Seed for reproducibility. None means non-deterministic.
        """
        if metric not in self.SUPPORTED_METRICS:
            raise ValueError(
                f"Unsupported metric '{metric}'. Choose from: {self.SUPPORTED_METRICS}"
            )
        if len(equity_curve) < 3:
            raise ValueError("equity_curve must have at least 3 data points.")

        self.equity_curve = equity_curve
        self.n_permutations = n_permutations
        self.metric = metric
        self.risk_free_rate = risk_free_rate
        self.rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _daily_returns(self) -> pd.Series:
        """Extract daily returns from the equity curve."""
        return PerformanceMetrics.daily_returns(self.equity_curve)

    def _curve_from_returns(
        self,
        returns: np.ndarray,
        start_value: float,
        timestamps: pd.DatetimeIndex,
    ) -> List[Tuple[datetime, float]]:
        """Reconstruct an equity curve from a return array."""
        values = start_value * np.cumprod(1 + returns)
        # Prepend the starting value with the first timestamp
        all_values = np.concatenate([[start_value], values])
        all_timestamps = [timestamps[0]] + list(timestamps[1:])
        # Pad or trim to match length
        n = min(len(all_timestamps), len(all_values))
        return list(zip(all_timestamps[:n], all_values[:n].tolist()))

    def _compute_metric(self, curve: List[Tuple[datetime, float]]) -> float:
        """Compute the target metric for a given equity curve."""
        if self.metric == 'sharpe_ratio':
            return PerformanceMetrics.sharpe_ratio(curve, self.risk_free_rate)
        elif self.metric == 'sortino_ratio':
            return PerformanceMetrics.sortino_ratio(curve, self.risk_free_rate)
        elif self.metric == 'calmar_ratio':
            return PerformanceMetrics.calmar_ratio(curve)
        elif self.metric == 'total_return':
            return PerformanceMetrics.total_return(curve[0][1], curve[-1][1])
        raise ValueError(f"Unknown metric: {self.metric}")  # unreachable

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        """
        Run the permutation test.

        Returns a dict with keys:
            observed       — metric value from the real backtest
            null_mean      — mean of the null (permuted) distribution
            null_std       — std of the null distribution
            null_values    — array of all permuted metric values (length = n_permutations)
            p_value        — fraction of permutations >= observed
            n_permutations — number of permutations run
            metric         — metric name tested
            significant    — bool: p_value < 0.05
        """
        returns = self._daily_returns()
        if len(returns) < 2:
            raise ValueError("Not enough daily returns to run permutation test.")

        timestamps = returns.index
        start_value = self.equity_curve[0][1]
        return_values = returns.values

        # Observed metric on the real (ordered) return series
        observed = self._compute_metric(self.equity_curve)
        logger.info(
            f"Permutation test: metric={self.metric}, observed={observed:.4f}, "
            f"n_permutations={self.n_permutations}"
        )

        # Build null distribution
        null_values = np.empty(self.n_permutations)
        for i in range(self.n_permutations):
            shuffled = self.rng.permutation(return_values)
            perm_curve = self._curve_from_returns(shuffled, start_value, timestamps)
            null_values[i] = self._compute_metric(perm_curve)

        p_value = float(np.mean(null_values >= observed))

        result = {
            'observed': observed,
            'null_mean': float(np.mean(null_values)),
            'null_std': float(np.std(null_values)),
            'null_values': null_values,
            'p_value': p_value,
            'n_permutations': self.n_permutations,
            'metric': self.metric,
            'significant': p_value < 0.05,
        }

        logger.info(
            f"  null mean={result['null_mean']:.4f}, "
            f"null std={result['null_std']:.4f}, "
            f"p-value={p_value:.4f}, significant={result['significant']}"
        )
        return result

    @staticmethod
    def summarize(result: Dict) -> str:
        """Return a formatted text summary of permutation test results."""
        lines = [
            "=" * 60,
            "RETURN PERMUTATION TEST",
            "=" * 60,
            f"  Metric tested:      {result['metric']}",
            f"  Observed value:     {result['observed']:>10.4f}",
            f"  Null distribution:",
            f"    Mean:             {result['null_mean']:>10.4f}",
            f"    Std dev:          {result['null_std']:>10.4f}",
            f"    Z-score:          {(result['observed'] - result['null_mean']) / result['null_std']:>10.2f}"
            if result['null_std'] > 0 else "    Z-score:               N/A",
            f"  Permutations:       {result['n_permutations']:>10d}",
            f"  P-value:            {result['p_value']:>10.4f}",
            f"  Significant:        {'YES (p < 0.05)' if result['significant'] else 'NO  (p >= 0.05)'}",
            "=" * 60,
        ]
        return "\n".join(lines)
