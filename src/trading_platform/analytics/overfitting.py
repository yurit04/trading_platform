"""
Overfitting detection tools for backtest analysis.

PermutationTest   — shuffles the daily equity-curve returns N times to build a
                    null distribution of a performance metric (Sharpe, Sortino, …).

MonteCarloTradeTest — takes the stitched out-of-sample round-trip trades from a
                      walk-forward run, reshuffles their order N times, and reports
                      the distribution of equity curves / drawdowns / return:drawdown
                      ratios.  The headline score is the *median* return:drawdown
                      ratio across all simulations.

BootstrapTradeTest — bootstrap (with-replacement) variant of MonteCarloTradeTest.
                     Each simulation draws n trades from the pool WITH replacement,
                     so the same trade may appear multiple times and some original
                     trades may not appear at all.  Reports the *median* Sharpe,
                     Sortino, Calmar, and Return-to-Drawdown across all simulations.
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
        z = (
            f"{(result['observed'] - result['null_mean']) / result['null_std']:>10.2f}"
            if result['null_std'] > 0 else "       N/A"
        )
        lines = [
            "=" * 60,
            "RETURN PERMUTATION TEST",
            "=" * 60,
            f"  Metric tested:      {result['metric']}",
            f"  Observed value:     {result['observed']:>10.4f}",
            f"  Null distribution:",
            f"    Mean:             {result['null_mean']:>10.4f}",
            f"    Std dev:          {result['null_std']:>10.4f}",
            f"    Z-score:          {z}",
            f"  Permutations:       {result['n_permutations']:>10d}",
            f"  P-value:            {result['p_value']:>10.4f}",
            f"  Significant:        {'YES (p < 0.05)' if result['significant'] else 'NO  (p >= 0.05)'}",
            "=" * 60,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------


class MonteCarloTradeTest:
    """
    Monte Carlo simulation on stitched out-of-sample walk-forward trades.

    Workflow expected from the caller
    ----------------------------------
    1. Run a walk-forward optimisation (N folds).
    2. For each OOS fold, collect the round-trip trades (list of dicts with
       at minimum a 'pnl' key in dollar terms).
    3. Concatenate all OOS trades into one list and pass here.
    4. Optionally check the gate: stitched return/drawdown > min_ratio.
    5. Call run() — trades are reshuffled n_simulations times; each shuffle
       produces a synthetic equity curve.
    6. The headline score is the *median* return/drawdown ratio across
       all simulations (not the ratio of the original stitched order).

    Assumptions / limitations
    --------------------------
    - All folds must use the same initial_capital so that dollar PnLs are
      on a comparable scale when stitched.
    - Trade PnL is treated as absolute dollars; percentage sizing drift
      across a long period is not modelled.
    - Open positions at the end of each fold are ignored (same limitation
      as the underlying round-trip calculation).
    """

    def __init__(
        self,
        trades: List[Dict],
        initial_capital: float,
        n_simulations: int = 1000,
        random_seed: Optional[int] = None,
    ):
        """
        Args:
            trades: List of round-trip trade dicts, each with a 'pnl' key
                    (dollar P&L for that trade).  Produced by
                    PerformanceMetrics._compute_round_trip_trades().
            initial_capital: Starting portfolio value used to compute
                             return / drawdown as percentages.
            n_simulations: Number of random orderings to simulate.
            random_seed: Seed for reproducibility.
        """
        if not trades:
            raise ValueError("trades list is empty — nothing to simulate.")
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive.")

        self.trades = trades
        self.initial_capital = initial_capital
        self.n_simulations = n_simulations
        self.rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _equity_from_pnls(pnls: np.ndarray, initial_capital: float) -> np.ndarray:
        """Build an equity array [initial, after_t1, after_t2, …] from a PnL vector."""
        return np.concatenate([[initial_capital], initial_capital + np.cumsum(pnls)])

    @staticmethod
    def _max_drawdown(equity: np.ndarray) -> float:
        """Max drawdown as a negative fraction (e.g. -0.20 = -20%)."""
        running_max = np.maximum.accumulate(equity)
        # Avoid division by zero if equity goes to 0
        with np.errstate(invalid='ignore', divide='ignore'):
            dd = np.where(running_max > 0, (equity - running_max) / running_max, 0.0)
        return float(dd.min())

    @staticmethod
    def _total_return(equity: np.ndarray) -> float:
        if equity[0] == 0:
            return 0.0
        return float((equity[-1] - equity[0]) / equity[0])

    @staticmethod
    def _ratio(total_return: float, max_drawdown: float) -> float:
        """Return / abs(drawdown).  Returns 0 if drawdown is zero and return <= 0."""
        if max_drawdown == 0:
            return float('inf') if total_return > 0 else 0.0
        return total_return / abs(max_drawdown)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observed_stats(self) -> Dict:
        """
        Stats for the stitched trades in their original (chronological) order.
        Used for the walk-forward gate check before running simulations.
        """
        pnls = np.array([t['pnl'] for t in self.trades])
        equity = self._equity_from_pnls(pnls, self.initial_capital)
        ret = self._total_return(equity)
        dd = self._max_drawdown(equity)
        return {
            'total_return': ret,
            'max_drawdown': dd,
            'return_drawdown_ratio': self._ratio(ret, dd),
            'n_trades': len(self.trades),
            'final_equity': float(equity[-1]),
        }

    def run(self) -> Dict:
        """
        Run the Monte Carlo simulation.

        Returns a dict with keys:
            observed            — stats for the stitched (original-order) trades
            median_ratio        — median return/drawdown across all simulations  ← headline
            sim_returns         — array(n_simulations) of simulated total returns
            sim_drawdowns       — array(n_simulations) of simulated max drawdowns
            sim_ratios          — array(n_simulations) of simulated return/drawdown ratios
            n_simulations       — number of simulations run
            n_trades            — number of trades used
            percentiles         — dict of p5/p25/p50/p75/p95 for ratio, return, drawdown
        """
        pnls = np.array([t['pnl'] for t in self.trades])
        n = len(pnls)

        logger.info(
            f"Monte Carlo trade simulation: n_trades={n}, "
            f"n_simulations={self.n_simulations}, initial_capital={self.initial_capital:,.2f}"
        )

        sim_returns = np.empty(self.n_simulations)
        sim_drawdowns = np.empty(self.n_simulations)
        sim_ratios = np.empty(self.n_simulations)

        for i in range(self.n_simulations):
            shuffled = self.rng.permutation(pnls)
            equity = self._equity_from_pnls(shuffled, self.initial_capital)
            ret = self._total_return(equity)
            dd = self._max_drawdown(equity)
            sim_returns[i] = ret
            sim_drawdowns[i] = dd
            sim_ratios[i] = self._ratio(ret, dd)

        median_ratio = float(np.median(sim_ratios))

        def pctiles(arr: np.ndarray) -> Dict:
            finite = arr[np.isfinite(arr)]
            if len(finite) == 0:
                return {p: float('nan') for p in ('p5', 'p25', 'p50', 'p75', 'p95')}
            return {
                'p5':  float(np.percentile(finite, 5)),
                'p25': float(np.percentile(finite, 25)),
                'p50': float(np.percentile(finite, 50)),
                'p75': float(np.percentile(finite, 75)),
                'p95': float(np.percentile(finite, 95)),
            }

        result = {
            'observed': self.observed_stats(),
            'median_ratio': median_ratio,
            'sim_returns': sim_returns,
            'sim_drawdowns': sim_drawdowns,
            'sim_ratios': sim_ratios,
            'n_simulations': self.n_simulations,
            'n_trades': n,
            'percentiles': {
                'ratio':    pctiles(sim_ratios),
                'return':   pctiles(sim_returns),
                'drawdown': pctiles(sim_drawdowns),
            },
        }

        logger.info(
            f"  median ratio={median_ratio:.4f}, "
            f"observed ratio={result['observed']['return_drawdown_ratio']:.4f}"
        )
        return result

    @staticmethod
    def summarize(result: Dict, min_ratio: float = 2.0) -> str:
        """Return a formatted text summary of Monte Carlo results."""
        obs = result['observed']
        pct = result['percentiles']

        gate = obs['return_drawdown_ratio'] >= min_ratio
        gate_str = f"PASS  ({obs['return_drawdown_ratio']:.2f} >= {min_ratio})" if gate \
                   else f"FAIL  ({obs['return_drawdown_ratio']:.2f} < {min_ratio})"

        def fmt_pct(v):
            return f"{v:>+8.2%}" if abs(v) != float('inf') and not (v != v) else f"{'N/A':>8}"

        lines = [
            "=" * 65,
            "MONTE CARLO TRADE SIMULATION",
            "=" * 65,
            f"  Trades used:        {result['n_trades']:>10d}",
            f"  Simulations:        {result['n_simulations']:>10d}",
            "",
            "  STITCHED OOS (original order)",
            f"    Total return:     {fmt_pct(obs['total_return'])}",
            f"    Max drawdown:     {fmt_pct(obs['max_drawdown'])}",
            f"    Return/Drawdown:  {obs['return_drawdown_ratio']:>10.2f}",
            f"    Gate (>= {min_ratio:.1f}):     {gate_str}",
            "",
            "  SIMULATION DISTRIBUTION  (return / drawdown ratio)",
            f"    p5:               {pct['ratio']['p5']:>10.2f}",
            f"    p25:              {pct['ratio']['p25']:>10.2f}",
            f"    Median (score):   {result['median_ratio']:>10.2f}   ← headline",
            f"    p75:              {pct['ratio']['p75']:>10.2f}",
            f"    p95:              {pct['ratio']['p95']:>10.2f}",
            "",
            "  SIMULATION DISTRIBUTION  (total return)",
            f"    p5 / p50 / p95:  "
            f" {fmt_pct(pct['return']['p5'])} / {fmt_pct(pct['return']['p50'])} / {fmt_pct(pct['return']['p95'])}",
            "",
            "  SIMULATION DISTRIBUTION  (max drawdown)",
            f"    p5 / p50 / p95:  "
            f" {fmt_pct(pct['drawdown']['p5'])} / {fmt_pct(pct['drawdown']['p50'])} / {fmt_pct(pct['drawdown']['p95'])}",
            "=" * 65,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------


class BootstrapTradeTest:
    """
    Bootstrap (with-replacement) Monte Carlo simulation on round-trip trades.

    Unlike MonteCarloTradeTest (which shuffles/permutes the existing trades
    without replacement), this test draws n trades WITH replacement for each
    simulation — so the same trade can appear multiple times and some original
    trades may not appear at all.  This is classical bootstrap resampling.

    Metrics computed per simulation path:
      - sharpe_ratio            mean excess per-trade return / std × ann_factor
      - sortino_ratio           mean excess / downside-std × ann_factor
      - calmar_ratio            annualised return / abs(max_drawdown)
      - return_drawdown_ratio   total_return / abs(max_drawdown)

    If ``trades_per_year`` is provided, Sharpe / Sortino are annualised
    (multiplied by sqrt(trades_per_year)) and Calmar uses CAGR instead of
    total return.  If omitted, Sharpe / Sortino are per-trade-step
    (unannualised) and Calmar equals return_drawdown_ratio.

    The headline output is the *median* of each metric across all simulations.
    """

    def __init__(
        self,
        trades: List[Dict],
        initial_capital: float,
        n_simulations: int = 1000,
        trades_per_year: Optional[float] = None,
        risk_free_rate: float = 0.02,
        random_seed: Optional[int] = None,
    ):
        """
        Args:
            trades: List of round-trip trade dicts, each with a 'pnl' key
                    (dollar P&L for that trade).  Produced by
                    PerformanceMetrics._compute_round_trip_trades().
            initial_capital: Starting portfolio value used to compute
                             return / drawdown as percentages.
            n_simulations: Number of bootstrap samples to draw.
            trades_per_year: Used to annualise Sharpe, Sortino, and Calmar.
                             If None, Sharpe/Sortino are per-trade-step and
                             Calmar equals return_drawdown_ratio.
            risk_free_rate: Annual risk-free rate (used only when
                            trades_per_year is provided).
            random_seed: Seed for reproducibility.
        """
        if not trades:
            raise ValueError("trades list is empty — nothing to simulate.")
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive.")

        self.trades = trades
        self.initial_capital = initial_capital
        self.n_simulations = n_simulations
        self.trades_per_year = trades_per_year
        self.risk_free_rate = risk_free_rate
        self.rng = np.random.default_rng(random_seed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _equity_from_pnls(pnls: np.ndarray, initial_capital: float) -> np.ndarray:
        """Build equity array [initial, after_t1, after_t2, …] from a PnL vector."""
        return np.concatenate([[initial_capital], initial_capital + np.cumsum(pnls)])

    @staticmethod
    def _trade_returns(equity: np.ndarray) -> np.ndarray:
        """Per-trade % returns: pnl[i] / equity_before_trade[i]."""
        pre_trade = equity[:-1]
        pnls = np.diff(equity)
        with np.errstate(invalid='ignore', divide='ignore'):
            returns = np.where(pre_trade > 0, pnls / pre_trade, 0.0)
        return returns

    @staticmethod
    def _max_drawdown(equity: np.ndarray) -> float:
        """Max drawdown as a negative fraction (e.g. -0.20 = -20%)."""
        running_max = np.maximum.accumulate(equity)
        with np.errstate(invalid='ignore', divide='ignore'):
            dd = np.where(running_max > 0, (equity - running_max) / running_max, 0.0)
        return float(dd.min())

    @staticmethod
    def _total_return(equity: np.ndarray) -> float:
        if equity[0] == 0:
            return 0.0
        return float((equity[-1] - equity[0]) / equity[0])

    def _ann_factor(self) -> float:
        """sqrt(trades_per_year) annualisation factor, or 1.0 if not set."""
        if self.trades_per_year and self.trades_per_year > 0:
            return float(np.sqrt(self.trades_per_year))
        return 1.0

    def _rf_per_trade(self) -> float:
        """Risk-free rate per trade step, or 0.0 if trades_per_year is not set."""
        if self.trades_per_year and self.trades_per_year > 0:
            return self.risk_free_rate / self.trades_per_year
        return 0.0

    def _compute_metrics(self, equity: np.ndarray) -> Dict:
        """Compute all four metrics from an equity array."""
        trade_rets = self._trade_returns(equity)
        n = len(trade_rets)
        ann = self._ann_factor()
        rf = self._rf_per_trade()

        total_ret = self._total_return(equity)
        max_dd = self._max_drawdown(equity)

        # Sharpe: mean excess / std × ann_factor
        excess = trade_rets - rf
        std = float(np.std(excess, ddof=1)) if n > 1 else 0.0
        sharpe = float(np.mean(excess) / std * ann) if std > 0 else 0.0

        # Sortino: mean excess / downside-vol × ann_factor
        # downside_vol uses all returns (zeros for positive), giving a conservative estimate
        downside = np.minimum(excess, 0.0)
        downside_var = float(np.mean(downside ** 2))
        downside_vol = float(np.sqrt(downside_var)) * ann if downside_var > 0 else 0.0
        sortino = float(np.mean(excess) * ann / downside_vol) if downside_vol > 0 else 0.0

        # Calmar: CAGR / abs(max_drawdown) when trades_per_year is known; else total_return
        if self.trades_per_year and self.trades_per_year > 0 and n > 0:
            annualized_ret = float((1.0 + total_ret) ** (self.trades_per_year / n) - 1.0)
        else:
            annualized_ret = total_ret

        if max_dd == 0:
            calmar = float('inf') if annualized_ret > 0 else 0.0
        else:
            calmar = annualized_ret / abs(max_dd)

        # Return / Drawdown
        if max_dd == 0:
            rdr = float('inf') if total_ret > 0 else 0.0
        else:
            rdr = total_ret / abs(max_dd)

        return {
            'sharpe': sharpe,
            'sortino': sortino,
            'calmar': calmar,
            'return_drawdown_ratio': rdr,
            'total_return': total_ret,
            'max_drawdown': max_dd,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observed_stats(self) -> Dict:
        """
        Metrics for the trades in their original (chronological) order.
        Useful for comparison against the bootstrapped distribution.
        """
        pnls = np.array([t['pnl'] for t in self.trades])
        equity = self._equity_from_pnls(pnls, self.initial_capital)
        stats = self._compute_metrics(equity)
        stats['n_trades'] = len(self.trades)
        stats['final_equity'] = float(equity[-1])
        return stats

    def run(self) -> Dict:
        """
        Run the bootstrap simulation.

        Returns a dict with keys:
            observed          — metrics on the original (ordered) trade sequence
            medians           — median of each metric across simulations
                                {'sharpe', 'sortino', 'calmar', 'return_drawdown_ratio'}
            percentiles       — per-metric {'p5', 'p25', 'p50', 'p75', 'p95'}
            n_simulations     — number of simulations run
            n_trades          — number of trades in the pool
            trades_per_year   — annualisation parameter (None if not provided)
            annualized        — True if annualisation was applied
        """
        pnls = np.array([t['pnl'] for t in self.trades])
        n = len(pnls)

        logger.info(
            f"Bootstrap trade simulation: n_trades={n}, "
            f"n_simulations={self.n_simulations}, "
            f"initial_capital={self.initial_capital:,.2f}, "
            f"trades_per_year={self.trades_per_year}"
        )

        sim_sharpe  = np.empty(self.n_simulations)
        sim_sortino = np.empty(self.n_simulations)
        sim_calmar  = np.empty(self.n_simulations)
        sim_rdr     = np.empty(self.n_simulations)

        for i in range(self.n_simulations):
            sampled = self.rng.choice(pnls, size=n, replace=True)
            equity = self._equity_from_pnls(sampled, self.initial_capital)
            m = self._compute_metrics(equity)
            sim_sharpe[i]  = m['sharpe']
            sim_sortino[i] = m['sortino']
            sim_calmar[i]  = m['calmar']
            sim_rdr[i]     = m['return_drawdown_ratio']

        def pctiles(arr: np.ndarray) -> Dict:
            finite = arr[np.isfinite(arr)]
            if len(finite) == 0:
                return {p: float('nan') for p in ('p5', 'p25', 'p50', 'p75', 'p95')}
            return {
                'p5':  float(np.percentile(finite, 5)),
                'p25': float(np.percentile(finite, 25)),
                'p50': float(np.percentile(finite, 50)),
                'p75': float(np.percentile(finite, 75)),
                'p95': float(np.percentile(finite, 95)),
            }

        def safe_median(arr: np.ndarray) -> float:
            finite = arr[np.isfinite(arr)]
            return float(np.median(finite)) if len(finite) > 0 else float('nan')

        annualized = bool(self.trades_per_year and self.trades_per_year > 0)
        medians = {
            'sharpe':                safe_median(sim_sharpe),
            'sortino':               safe_median(sim_sortino),
            'calmar':                safe_median(sim_calmar),
            'return_drawdown_ratio': safe_median(sim_rdr),
        }

        result = {
            'observed':        self.observed_stats(),
            'medians':         medians,
            'percentiles': {
                'sharpe':                pctiles(sim_sharpe),
                'sortino':               pctiles(sim_sortino),
                'calmar':                pctiles(sim_calmar),
                'return_drawdown_ratio': pctiles(sim_rdr),
            },
            'n_simulations':   self.n_simulations,
            'n_trades':        n,
            'trades_per_year': self.trades_per_year,
            'annualized':      annualized,
        }

        logger.info(
            f"  medians — sharpe={medians['sharpe']:.4f}, "
            f"sortino={medians['sortino']:.4f}, "
            f"calmar={medians['calmar']:.4f}, "
            f"rdr={medians['return_drawdown_ratio']:.4f}"
        )
        return result

    @staticmethod
    def summarize(result: Dict) -> str:
        """Return a formatted text summary of bootstrap simulation results."""
        obs = result['observed']
        med = result['medians']
        pct = result['percentiles']
        ann = result['annualized']
        tpy = result['trades_per_year']

        ann_note = (
            f"annualised ({tpy:.0f} trades/yr)" if ann
            else "per-trade step, unannualised"
        )

        def fv(v: float, as_pct: bool = False) -> str:
            """Format a float value; return 'N/A' for nan/inf."""
            if v != v or not np.isfinite(v):
                return f"{'N/A':>10}"
            if as_pct:
                return f"{v:>+10.2%}"
            return f"{v:>10.4f}"

        col_w = 10
        metric_w = 24
        header = (
            f"  {'Metric':<{metric_w}}"
            f"  {'Observed':>{col_w}}"
            f"  {'Median':>{col_w}}"
            f"  {'p5':>{col_w}}  {'p25':>{col_w}}  {'p50':>{col_w}}"
            f"  {'p75':>{col_w}}  {'p95':>{col_w}}"
        )
        sep = "  " + "-" * (metric_w + 7 * (col_w + 2))

        def metric_row(label: str, key: str, as_pct: bool = False) -> str:
            p = pct[key]
            return (
                f"  {label:<{metric_w}}"
                f"  {fv(obs[key], as_pct)}"
                f"  {fv(med[key], as_pct)}"
                f"  {fv(p['p5'], as_pct)}  {fv(p['p25'], as_pct)}  {fv(p['p50'], as_pct)}"
                f"  {fv(p['p75'], as_pct)}  {fv(p['p95'], as_pct)}"
            )

        lines = [
            "=" * 80,
            "BOOTSTRAP MONTE CARLO TRADE SIMULATION",
            "=" * 80,
            f"  Trades in pool:    {result['n_trades']:>10d}",
            f"  Simulations:       {result['n_simulations']:>10d}",
            f"  Sharpe / Sortino:  {ann_note}",
            "",
            header,
            sep,
            metric_row("Sharpe",               "sharpe"),
            metric_row("Sortino",              "sortino"),
            metric_row("Calmar",               "calmar"),
            metric_row("Return / Drawdown",    "return_drawdown_ratio"),
            sep,
            f"  {'Observed equity stats':<{metric_w}}",
            f"    Total return:    {fv(obs['total_return'], as_pct=True)}",
            f"    Max drawdown:    {fv(obs['max_drawdown'], as_pct=True)}",
            f"    Final equity:    ${obs['final_equity']:>12,.2f}",
            "=" * 80,
        ]
        return "\n".join(lines)
