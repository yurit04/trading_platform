#!/usr/bin/env python
"""
Strategy parameter optimization script.

Supports grid search and walk-forward analysis over strategy parameters.

Usage:
    python scripts/optimize.py --config config/strategies/momentum.yaml
    python scripts/optimize.py --config config/strategies/momentum.yaml --metric sharpe_ratio
    python scripts/optimize.py --config config/strategies/momentum.yaml --walk-forward 4
    python scripts/optimize.py --config config/strategies/momentum.yaml --no-report
"""
import argparse
import sys
import itertools
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
import yaml
import logging
import copy

# Add project root and src to path
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)
sys.path.insert(0, str(Path(project_root) / 'src'))

from trading_platform.core.engine import BacktestEngine
from trading_platform.utils.logging import setup_logging


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Optimize strategy parameters')

    parser.add_argument(
        '--config', type=str, required=True,
        help='Path to strategy configuration file'
    )
    parser.add_argument(
        '--metric', type=str, default='sharpe_ratio',
        help='Metric to optimize (default: sharpe_ratio)'
    )
    parser.add_argument(
        '--walk-forward', type=int, default=0,
        help='Number of walk-forward folds (0 = single backtest)'
    )
    parser.add_argument(
        '--train-ratio', type=float, default=0.7,
        help='Train/test split ratio for walk-forward (default: 0.7)'
    )
    parser.add_argument(
        '--no-report', action='store_true',
        help='Skip saving detailed results'
    )
    parser.add_argument(
        '--output', type=str, default='results/optimization',
        help='Output directory for results'
    )
    parser.add_argument(
        '--verbose', action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--top-n', type=int, default=10,
        help='Show top N parameter combinations (default: 10)'
    )

    return parser.parse_args()


def build_param_grid(config: dict) -> Tuple[List[str], List[List]]:
    """
    Build parameter grid from optimization config section.

    Config format:
        optimization:
          parameters:
            lookback_period: [10, 15, 20, 30]
            top_n: [5, 10]
            rebalance_days: [5, 10, 20]

    Returns:
        (param_names, param_combinations)
    """
    opt_config = config.get('optimization', {})
    param_ranges = opt_config.get('parameters', {})

    if not param_ranges:
        raise ValueError(
            "No optimization parameters found. Add an 'optimization.parameters' "
            "section to your config with parameter names mapped to lists of values."
        )

    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name] for name in param_names]
    combinations = list(itertools.product(*param_values))

    return param_names, combinations


def run_single_backtest(
    config: dict,
    param_overrides: Dict[str, Any],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    logger: logging.Logger
) -> Dict[str, Any]:
    """
    Run a single backtest with the given parameter overrides.

    Returns:
        Results dict with all metrics
    """
    # Deep copy config and apply overrides
    run_config = copy.deepcopy(config)
    run_config.setdefault('parameters', {}).update(param_overrides)

    engine = BacktestEngine(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        config=run_config
    )

    # Load strategy
    strategy_class_path = run_config.get('strategy', {}).get('class')
    if not strategy_class_path:
        raise ValueError("No strategy class specified in configuration")

    module_path, class_name = strategy_class_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)

    strategy_params = run_config.get('parameters', {})
    universe_config = run_config.get('universe', {})

    strategy = strategy_class(
        universe=universe_config.get('symbols', []),
        **strategy_params
    )

    engine.add_strategy(strategy)
    engine.initialize()

    results = engine.start()

    # Remove non-serializable raw data
    results.pop('equity_curve', None)
    results.pop('trade_history', None)
    results.pop('positions', None)
    results.pop('risk_metrics', None)

    return results


def grid_search(
    config: dict,
    param_names: List[str],
    combinations: List[tuple],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    target_metric: str,
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    """
    Run grid search over all parameter combinations.

    Returns:
        List of result dicts, each with 'params' and metric values
    """
    total = len(combinations)
    logger.info(f"Running grid search: {total} combinations")
    logger.info(f"Parameters: {param_names}")
    logger.info(f"Optimizing for: {target_metric}")

    all_results = []

    for i, combo in enumerate(combinations, 1):
        param_overrides = dict(zip(param_names, combo))
        param_str = ', '.join(f'{k}={v}' for k, v in param_overrides.items())
        logger.info(f"  [{i}/{total}] {param_str}")

        try:
            results = run_single_backtest(
                config, param_overrides, start_date, end_date,
                initial_capital, logger
            )
            results['params'] = param_overrides
            metric_val = results.get(target_metric, float('-inf'))
            logger.info(f"    {target_metric} = {metric_val:.4f}")
            all_results.append(results)
        except Exception as e:
            logger.warning(f"    FAILED: {e}")
            all_results.append({
                'params': param_overrides,
                target_metric: float('-inf'),
                'error': str(e)
            })

    return all_results


def walk_forward_analysis(
    config: dict,
    param_names: List[str],
    combinations: List[tuple],
    full_start: datetime,
    full_end: datetime,
    initial_capital: float,
    target_metric: str,
    n_folds: int,
    train_ratio: float,
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    """
    Walk-forward optimization.

    Splits the date range into n_folds windows. For each window:
    1. Optimize on the training portion
    2. Test the best params on the out-of-sample portion

    Returns:
        List of fold results with train/test metrics
    """
    total_days = (full_end - full_start).days
    fold_days = total_days // n_folds

    logger.info(f"Walk-forward analysis: {n_folds} folds, {fold_days} days each")
    logger.info(f"Train ratio: {train_ratio:.0%}")

    fold_results = []

    for fold in range(n_folds):
        fold_start = full_start + timedelta(days=fold * fold_days)
        fold_end = fold_start + timedelta(days=fold_days)
        if fold == n_folds - 1:
            fold_end = full_end

        train_days = int((fold_end - fold_start).days * train_ratio)
        train_end = fold_start + timedelta(days=train_days)
        test_start = train_end + timedelta(days=1)

        logger.info(f"\n  Fold {fold + 1}/{n_folds}")
        logger.info(f"    Train: {fold_start.date()} to {train_end.date()}")
        logger.info(f"    Test:  {test_start.date()} to {fold_end.date()}")

        # Optimize on training set
        train_results = grid_search(
            config, param_names, combinations,
            fold_start, train_end, initial_capital,
            target_metric, logger
        )

        # Find best params from training
        best_train = max(
            train_results,
            key=lambda r: r.get(target_metric, float('-inf'))
        )
        best_params = best_train['params']
        logger.info(f"    Best train params: {best_params}")
        logger.info(f"    Best train {target_metric}: {best_train.get(target_metric, 0):.4f}")

        # Test best params on out-of-sample
        try:
            test_result = run_single_backtest(
                config, best_params, test_start, fold_end,
                initial_capital, logger
            )
            test_metric = test_result.get(target_metric, 0)
            logger.info(f"    Test {target_metric}: {test_metric:.4f}")
        except Exception as e:
            logger.warning(f"    Test FAILED: {e}")
            test_result = {target_metric: float('-inf'), 'error': str(e)}
            test_metric = float('-inf')

        fold_results.append({
            'fold': fold + 1,
            'train_start': fold_start.strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'test_start': test_start.strftime('%Y-%m-%d'),
            'test_end': fold_end.strftime('%Y-%m-%d'),
            'best_params': best_params,
            f'train_{target_metric}': best_train.get(target_metric, 0),
            f'test_{target_metric}': test_metric,
            'test_total_return': test_result.get('total_return', 0),
            'test_max_drawdown': test_result.get('max_drawdown', 0),
            'test_num_trades': test_result.get('num_trades', 0),
        })

    return fold_results


def display_grid_results(
    results: List[Dict[str, Any]],
    target_metric: str,
    top_n: int,
    logger: logging.Logger
) -> None:
    """Display ranked grid search results."""
    sorted_results = sorted(
        results,
        key=lambda r: r.get(target_metric, float('-inf')),
        reverse=True
    )

    logger.info("")
    logger.info("=" * 80)
    logger.info("OPTIMIZATION RESULTS")
    logger.info("=" * 80)
    logger.info(f"  Target metric: {target_metric}")
    logger.info(f"  Total combinations tested: {len(results)}")
    logger.info("")

    logger.info(f"  TOP {min(top_n, len(sorted_results))} PARAMETER COMBINATIONS")
    logger.info("-" * 80)

    for rank, result in enumerate(sorted_results[:top_n], 1):
        params = result.get('params', {})
        param_str = ', '.join(f'{k}={v}' for k, v in params.items())
        metric_val = result.get(target_metric, 0)
        total_ret = result.get('total_return', 0)
        max_dd = result.get('max_drawdown', 0)
        n_trades = result.get('num_trades', 0)

        logger.info(f"  #{rank:>2d}  {target_metric}={metric_val:>8.4f}  "
                     f"return={total_ret:>8.2%}  maxDD={max_dd:>8.2%}  "
                     f"trades={n_trades:>4d}  |  {param_str}")

    logger.info("=" * 80)


def display_walk_forward_results(
    fold_results: List[Dict[str, Any]],
    target_metric: str,
    logger: logging.Logger
) -> None:
    """Display walk-forward analysis results."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("WALK-FORWARD ANALYSIS RESULTS")
    logger.info("=" * 80)

    for fold in fold_results:
        logger.info(f"\n  Fold {fold['fold']}: "
                     f"Train {fold['train_start']} to {fold['train_end']} | "
                     f"Test {fold['test_start']} to {fold['test_end']}")
        params = fold['best_params']
        param_str = ', '.join(f'{k}={v}' for k, v in params.items())
        logger.info(f"    Best params: {param_str}")
        logger.info(f"    Train {target_metric}: {fold.get(f'train_{target_metric}', 0):>8.4f}")
        logger.info(f"    Test  {target_metric}: {fold.get(f'test_{target_metric}', 0):>8.4f}")
        logger.info(f"    Test  return: {fold.get('test_total_return', 0):>8.2%}  "
                     f"maxDD: {fold.get('test_max_drawdown', 0):>8.2%}  "
                     f"trades: {fold.get('test_num_trades', 0)}")

    # Summary
    test_metrics = [f.get(f'test_{target_metric}', 0) for f in fold_results]
    valid = [m for m in test_metrics if m != float('-inf')]
    if valid:
        avg_metric = sum(valid) / len(valid)
        logger.info(f"\n  Average OOS {target_metric}: {avg_metric:.4f}")
    logger.info("=" * 80)


def main():
    """Main optimization function."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 80)
    logger.info("Strategy Parameter Optimization")
    logger.info("=" * 80)

    config = load_config(args.config)
    logger.info(f"Loaded configuration from: {args.config}")

    # Parse dates
    backtest_cfg = config.get('backtest', {})
    start_date = datetime.strptime(backtest_cfg.get('start_date', '2020-01-01'), '%Y-%m-%d')
    end_date = datetime.strptime(backtest_cfg.get('end_date', '2023-12-31'), '%Y-%m-%d')
    initial_capital = backtest_cfg.get('initial_capital', 1_000_000)

    logger.info(f"Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Capital: ${initial_capital:,.2f}")
    logger.info(f"Metric: {args.metric}")

    # Build parameter grid
    try:
        param_names, combinations = build_param_grid(config)
    except ValueError as e:
        logger.error(str(e))
        return 1

    logger.info(f"Parameter grid: {len(combinations)} combinations")
    for name in param_names:
        vals = config['optimization']['parameters'][name]
        logger.info(f"  {name}: {vals}")

    # Suppress per-run logging noise
    logging.getLogger('trading_platform').setLevel(logging.WARNING)

    if args.walk_forward > 0:
        # Walk-forward analysis
        fold_results = walk_forward_analysis(
            config, param_names, combinations,
            start_date, end_date, initial_capital,
            args.metric, args.walk_forward, args.train_ratio,
            logger
        )
        display_walk_forward_results(fold_results, args.metric, logger)

        if not args.no_report:
            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"walkforward_{timestamp}.yaml"
            with open(output_file, 'w') as f:
                yaml.dump(fold_results, f, default_flow_style=False)
            logger.info(f"Results saved to: {output_file}")
    else:
        # Simple grid search
        results = grid_search(
            config, param_names, combinations,
            start_date, end_date, initial_capital,
            args.metric, logger
        )
        display_grid_results(results, args.metric, args.top_n, logger)

        if not args.no_report:
            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"optimization_{timestamp}.yaml"

            # Serialize results (strip non-serializable)
            save_results = []
            for r in sorted(results, key=lambda x: x.get(args.metric, float('-inf')), reverse=True):
                entry = {}
                for k, v in r.items():
                    if isinstance(v, datetime):
                        entry[k] = v.strftime('%Y-%m-%d')
                    elif isinstance(v, float) and (v == float('inf') or v == float('-inf')):
                        entry[k] = str(v)
                    else:
                        entry[k] = v
                save_results.append(entry)

            with open(output_file, 'w') as f:
                yaml.dump(save_results, f, default_flow_style=False)
            logger.info(f"Results saved to: {output_file}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
