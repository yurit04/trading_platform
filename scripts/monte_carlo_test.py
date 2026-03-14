#!/usr/bin/env python
"""
Walk-forward OOS trade collection + Monte Carlo simulation.

Two simulation modes are supported (--mode):

  shuffle   (default)
    Reshuffles the OOS trade sequence N times without replacement.
    Headline score: median return/drawdown ratio.

  bootstrap
    Samples N trades WITH replacement for each simulation (same trade may
    appear multiple times; some original trades may not appear at all).
    Reports median Sharpe, Sortino, Calmar, and Return-to-Drawdown.

Workflow:
  1. Run a walk-forward optimisation over the full date range.
     For each fold: optimise on the training window, then run the best
     parameters on the out-of-sample window and collect the round-trip trades.
  2. Stitch all OOS round-trip trades together into one sequence.
  3. Gate check: the stitched return/drawdown must exceed --min-ratio (default 2.0).
  4. Run the selected Monte Carlo simulation.
  5. Report median metric(s) and full percentile distribution.

Usage:
    python scripts/monte_carlo_test.py --config config/strategies/momentum.yaml
    python scripts/monte_carlo_test.py --config config/strategies/momentum.yaml --folds 6
    python scripts/monte_carlo_test.py --config config/strategies/momentum.yaml \\
        --folds 5 --train-ratio 0.7 --simulations 2000 --min-ratio 2.0 --seed 42
    python scripts/monte_carlo_test.py --config config/strategies/momentum.yaml \\
        --no-gate --output results/mc/momentum_mc.yaml
    python scripts/monte_carlo_test.py --config config/strategies/momentum.yaml \\
        --mode bootstrap --trades-per-year 52
"""
import argparse
import copy
import itertools
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml
import logging

project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)
sys.path.insert(0, str(Path(project_root) / 'src'))

from trading_platform.core.engine import BacktestEngine
from trading_platform.analytics.metrics import PerformanceMetrics
from trading_platform.analytics.overfitting import MonteCarloTradeTest, BootstrapTradeTest
from trading_platform.utils.logging import setup_logging


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description='Walk-forward OOS trade collection + Monte Carlo simulation'
    )
    parser.add_argument('--config', type=str, required=True,
                        help='Path to strategy configuration file')
    parser.add_argument('--folds', type=int, default=5,
                        help='Number of walk-forward folds (default: 5)')
    parser.add_argument('--train-ratio', type=float, default=0.7,
                        help='Fraction of each fold used for training (default: 0.7)')
    parser.add_argument('--opt-metric', type=str, default='sharpe_ratio',
                        help='Metric used to pick best params in training (default: sharpe_ratio)')
    parser.add_argument('--mode', type=str, default='shuffle',
                        choices=['shuffle', 'bootstrap'],
                        help='Simulation mode: shuffle (permutation, no replacement) or '
                             'bootstrap (with replacement, reports Sharpe/Sortino/Calmar/RDR). '
                             'Default: shuffle')
    parser.add_argument('--trades-per-year', type=float, default=None,
                        help='Expected trades per year; used to annualise Sharpe, Sortino, '
                             'and Calmar in bootstrap mode. If omitted, metrics are '
                             'per-trade-step (unannualised).')
    parser.add_argument('--simulations', type=int, default=1000,
                        help='Number of Monte Carlo simulations (default: 1000)')
    parser.add_argument('--min-ratio', type=float, default=2.0,
                        help='Minimum return/drawdown required on stitched OOS (default: 2.0)')
    parser.add_argument('--no-gate', action='store_true',
                        help='Run Monte Carlo even if the gate check fails')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility')
    parser.add_argument('--output', type=str, default=None,
                        help='Save summary results to this YAML file')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose logging')
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Backtest helpers
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def _load_strategy(config: dict, param_overrides: Dict[str, Any]):
    """Instantiate the strategy class from config, applying param_overrides."""
    class_path = config.get('strategy', {}).get('class')
    if not class_path:
        raise ValueError("No strategy class in configuration.")
    module_path, class_name = class_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)

    params = dict(config.get('parameters', {}))
    params.update(param_overrides)
    universe = config.get('universe', {}).get('symbols', [])
    return strategy_class(universe=universe, **params)


def _run_backtest(
    config: dict,
    param_overrides: Dict[str, Any],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
) -> Dict[str, Any]:
    """Run one backtest and return the full results dict (including trade_history)."""
    run_config = copy.deepcopy(config)
    run_config.setdefault('parameters', {}).update(param_overrides)

    engine = BacktestEngine(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        config=run_config,
    )
    engine.add_strategy(_load_strategy(run_config, param_overrides))
    engine.initialize()
    return engine.start()


# ---------------------------------------------------------------------------
# Walk-forward with OOS trade collection
# ---------------------------------------------------------------------------

def _build_param_grid(config: dict) -> Tuple[List[str], List[tuple]]:
    """Build (param_names, combinations) from config optimization section."""
    param_ranges = config.get('optimization', {}).get('parameters', {})
    if not param_ranges:
        raise ValueError(
            "No 'optimization.parameters' section found in config. "
            "Add parameter ranges to enable walk-forward optimisation."
        )
    names = list(param_ranges.keys())
    combos = list(itertools.product(*[param_ranges[n] for n in names]))
    return names, combos


def _best_params_on_window(
    config: dict,
    param_names: List[str],
    combinations: List[tuple],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    metric: str,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """
    Grid-search over param combinations on a training window.
    Returns the param dict that maximises `metric`.
    """
    best_val = float('-inf')
    best_params = dict(zip(param_names, combinations[0]))

    for combo in combinations:
        params = dict(zip(param_names, combo))
        try:
            results = _run_backtest(config, params, start_date, end_date, initial_capital)
            val = results.get(metric, float('-inf'))
            if val > best_val:
                best_val = val
                best_params = params
        except Exception as e:
            logger.debug(f"    Training run failed ({params}): {e}")

    return best_params


def walk_forward_collect_trades(
    config: dict,
    param_names: List[str],
    combinations: List[tuple],
    full_start: datetime,
    full_end: datetime,
    initial_capital: float,
    n_folds: int,
    train_ratio: float,
    opt_metric: str,
    logger: logging.Logger,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Walk-forward optimisation that collects round-trip trades from each OOS fold.

    Returns:
        (fold_summaries, all_oos_trades)
        fold_summaries — list of per-fold dicts (dates, best params, OOS metrics)
        all_oos_trades — stitched list of round-trip trade dicts from all OOS windows
    """
    total_days = (full_end - full_start).days
    fold_days = total_days // n_folds
    logger.info(f"Walk-forward: {n_folds} folds × {fold_days} days, train ratio={train_ratio:.0%}")

    fold_summaries = []
    all_oos_trades: List[Dict] = []

    for fold_idx in range(n_folds):
        fold_start = full_start + timedelta(days=fold_idx * fold_days)
        fold_end = fold_start + timedelta(days=fold_days)
        if fold_idx == n_folds - 1:
            fold_end = full_end

        train_days = int((fold_end - fold_start).days * train_ratio)
        train_end = fold_start + timedelta(days=train_days)
        oos_start = train_end + timedelta(days=1)

        logger.info(
            f"\n  Fold {fold_idx + 1}/{n_folds} — "
            f"train {fold_start.date()}→{train_end.date()}, "
            f"OOS {oos_start.date()}→{fold_end.date()}"
        )

        # --- training: find best params ---
        logger.info(f"    Optimising {len(combinations)} combinations on training window...")
        best_params = _best_params_on_window(
            config, param_names, combinations,
            fold_start, train_end, initial_capital, opt_metric, logger
        )
        logger.info(f"    Best params: {best_params}")

        # --- OOS: run with best params and collect trades ---
        try:
            oos_results = _run_backtest(
                config, best_params, oos_start, fold_end, initial_capital
            )
        except Exception as e:
            logger.warning(f"    OOS backtest failed: {e}")
            fold_summaries.append({
                'fold': fold_idx + 1,
                'oos_start': oos_start.strftime('%Y-%m-%d'),
                'oos_end': fold_end.strftime('%Y-%m-%d'),
                'best_params': best_params,
                'error': str(e),
            })
            continue

        # Convert FillEvents → round-trip trades
        raw_trade_history = oos_results.get('trade_history', [])
        round_trips = PerformanceMetrics._compute_round_trip_trades(raw_trade_history)

        oos_return = oos_results.get('total_return', 0.0)
        oos_dd = oos_results.get('max_drawdown', 0.0)
        oos_ratio = oos_return / abs(oos_dd) if oos_dd != 0 else 0.0

        logger.info(
            f"    OOS: return={oos_return:+.2%}, maxDD={oos_dd:.2%}, "
            f"ratio={oos_ratio:.2f}, trades={len(round_trips)}"
        )

        all_oos_trades.extend(round_trips)
        fold_summaries.append({
            'fold': fold_idx + 1,
            'train_start': fold_start.strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'oos_start': oos_start.strftime('%Y-%m-%d'),
            'oos_end': fold_end.strftime('%Y-%m-%d'),
            'best_params': best_params,
            'oos_total_return': oos_return,
            'oos_max_drawdown': oos_dd,
            'oos_return_drawdown_ratio': oos_ratio,
            'oos_num_trades': len(round_trips),
        })

    return fold_summaries, all_oos_trades


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def display_fold_summary(fold_summaries: List[Dict], logger: logging.Logger) -> None:
    logger.info("")
    logger.info("=" * 70)
    logger.info("WALK-FORWARD OOS SUMMARY")
    logger.info("=" * 70)
    for fold in fold_summaries:
        if 'error' in fold:
            logger.info(f"  Fold {fold['fold']}: ERROR — {fold['error']}")
            continue
        params_str = ', '.join(f"{k}={v}" for k, v in fold['best_params'].items())
        logger.info(
            f"  Fold {fold['fold']}  OOS {fold['oos_start']} → {fold['oos_end']}"
        )
        logger.info(
            f"    Params:  {params_str}"
        )
        logger.info(
            f"    Return:  {fold['oos_total_return']:+.2%}   "
            f"MaxDD: {fold['oos_max_drawdown']:.2%}   "
            f"Ratio: {fold['oos_return_drawdown_ratio']:.2f}   "
            f"Trades: {fold['oos_num_trades']}"
        )
    logger.info("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("Walk-Forward + Monte Carlo Overfitting Test")
    logger.info("=" * 70)

    config = _load_config(args.config)
    logger.info(f"Config:      {args.config}")
    logger.info(f"Mode:        {args.mode}")
    logger.info(f"Folds:       {args.folds}   Train ratio: {args.train_ratio:.0%}")
    logger.info(f"Opt metric:  {args.opt_metric}")
    logger.info(f"Simulations: {args.simulations}   Min ratio gate: {args.min_ratio}")
    if args.mode == 'bootstrap' and args.trades_per_year:
        logger.info(f"Trades/yr:   {args.trades_per_year}")

    backtest_cfg = config.get('backtest', {})
    start_date = datetime.strptime(backtest_cfg.get('start_date', '2020-01-01'), '%Y-%m-%d')
    end_date   = datetime.strptime(backtest_cfg.get('end_date',   '2023-12-31'), '%Y-%m-%d')
    initial_capital = backtest_cfg.get('initial_capital', 1_000_000)

    logger.info(f"Period:      {start_date.date()} → {end_date.date()}")
    logger.info(f"Capital:     ${initial_capital:,.2f}")

    # Build parameter grid
    try:
        param_names, combinations = _build_param_grid(config)
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"Param grid:  {len(combinations)} combinations across {param_names}")

    # Silence per-run engine noise
    logging.getLogger('trading_platform').setLevel(logging.WARNING)

    # --- Step 1: walk-forward ---
    logger.info("\nRunning walk-forward optimisation...")
    fold_summaries, all_oos_trades = walk_forward_collect_trades(
        config, param_names, combinations,
        start_date, end_date, initial_capital,
        args.folds, args.train_ratio, args.opt_metric, logger
    )

    logging.getLogger('trading_platform').setLevel(logging.INFO)
    display_fold_summary(fold_summaries, logger)

    if not all_oos_trades:
        logger.error("No OOS trades collected — cannot run Monte Carlo.")
        return 1

    logger.info(f"\nTotal OOS trades collected: {len(all_oos_trades)}")

    # --- Step 2: gate check on stitched OOS ---
    # Use MonteCarloTradeTest for the gate check regardless of mode (it only
    # calls observed_stats(), which is the same calculation for both modes).
    gate_test = MonteCarloTradeTest(
        trades=all_oos_trades,
        initial_capital=initial_capital,
        n_simulations=args.simulations,
        random_seed=args.seed,
    )
    obs_gate = gate_test.observed_stats()
    gate_pass = obs_gate['return_drawdown_ratio'] >= args.min_ratio

    logger.info(
        f"\nStitched OOS — return: {obs_gate['total_return']:+.2%}, "
        f"maxDD: {obs_gate['max_drawdown']:.2%}, "
        f"ratio: {obs_gate['return_drawdown_ratio']:.2f}  "
        f"({'PASS' if gate_pass else 'FAIL'} gate >= {args.min_ratio})"
    )

    if not gate_pass and not args.no_gate:
        logger.warning(
            f"\nGate FAILED: stitched OOS return/drawdown {obs_gate['return_drawdown_ratio']:.2f} "
            f"< {args.min_ratio}. Stopping here.\n"
            f"Use --no-gate to run Monte Carlo anyway."
        )
        return 1

    # --- Step 3: simulation ---
    logger.info(f"\nRunning {args.simulations} {args.mode} simulations...")

    if args.mode == 'bootstrap':
        sim = BootstrapTradeTest(
            trades=all_oos_trades,
            initial_capital=initial_capital,
            n_simulations=args.simulations,
            trades_per_year=args.trades_per_year,
            random_seed=args.seed,
        )
        result = sim.run()
        print()
        print(BootstrapTradeTest.summarize(result))
    else:
        sim = MonteCarloTradeTest(
            trades=all_oos_trades,
            initial_capital=initial_capital,
            n_simulations=args.simulations,
            random_seed=args.seed,
        )
        result = sim.run()
        print()
        print(MonteCarloTradeTest.summarize(result, min_ratio=args.min_ratio))

    # --- Optional: save to YAML ---
    if args.output:
        if args.mode == 'bootstrap':
            save = {
                'config': args.config,
                'mode': args.mode,
                'folds': args.folds,
                'train_ratio': args.train_ratio,
                'opt_metric': args.opt_metric,
                'min_ratio': args.min_ratio,
                'n_simulations': args.simulations,
                'trades_per_year': args.trades_per_year,
                'n_trades': result['n_trades'],
                'gate_pass': gate_pass,
                'observed': result['observed'],
                'medians': result['medians'],
                'percentiles': result['percentiles'],
                'fold_summaries': fold_summaries,
            }
        else:
            save = {
                'config': args.config,
                'mode': args.mode,
                'folds': args.folds,
                'train_ratio': args.train_ratio,
                'opt_metric': args.opt_metric,
                'min_ratio': args.min_ratio,
                'n_simulations': args.simulations,
                'n_trades': result['n_trades'],
                'gate_pass': gate_pass,
                'observed': result['observed'],
                'median_ratio': result['median_ratio'],
                'percentiles': result['percentiles'],
                'fold_summaries': fold_summaries,
            }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w') as f:
            yaml.dump(save, f, default_flow_style=False)
        logger.info(f"\nResults saved to: {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
