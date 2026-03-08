#!/usr/bin/env python
"""
Return permutation test for strategy overfitting detection.

Runs the strategy backtest once, then shuffles its daily return series
N times to build a null distribution of the chosen performance metric.
Reports the p-value: probability of matching or exceeding the observed
metric by random chance.

Usage:
    python scripts/permutation_test.py --config config/strategies/momentum.yaml
    python scripts/permutation_test.py --config config/strategies/momentum.yaml --metric sortino_ratio
    python scripts/permutation_test.py --config config/strategies/momentum.yaml --permutations 2000 --seed 42
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime
import yaml
import logging
import numpy as np

project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)
sys.path.insert(0, str(Path(project_root) / 'src'))

from trading_platform.core.engine import BacktestEngine
from trading_platform.analytics.overfitting import PermutationTest
from trading_platform.utils.logging import setup_logging


def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def parse_args():
    parser = argparse.ArgumentParser(description='Return permutation test for overfitting detection')

    parser.add_argument('--config', type=str, required=True,
                        help='Path to strategy configuration file')
    parser.add_argument('--metric', type=str, default='sharpe_ratio',
                        choices=PermutationTest.SUPPORTED_METRICS,
                        help='Performance metric to test (default: sharpe_ratio)')
    parser.add_argument('--permutations', type=int, default=1000,
                        help='Number of random permutations (default: 1000)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility')
    parser.add_argument('--risk-free-rate', type=float, default=0.02,
                        help='Annual risk-free rate for Sharpe/Sortino (default: 0.02)')
    parser.add_argument('--output', type=str, default=None,
                        help='Save results to this YAML file path')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose logging')

    return parser.parse_args()


def run_backtest(config: dict, logger: logging.Logger):
    """Run a single backtest and return (results, equity_curve)."""
    backtest_cfg = config.get('backtest', {})
    start_date = datetime.strptime(backtest_cfg.get('start_date', '2020-01-01'), '%Y-%m-%d')
    end_date = datetime.strptime(backtest_cfg.get('end_date', '2023-12-31'), '%Y-%m-%d')
    initial_capital = backtest_cfg.get('initial_capital', 1_000_000)

    logger.info(f"Backtest period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Initial capital: ${initial_capital:,.2f}")

    engine = BacktestEngine(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        config=config,
    )

    strategy_class_path = config.get('strategy', {}).get('class')
    if not strategy_class_path:
        raise ValueError("No strategy class specified in configuration")

    module_path, class_name = strategy_class_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)

    strategy = strategy_class(
        universe=config.get('universe', {}).get('symbols', []),
        **config.get('parameters', {}),
    )
    engine.add_strategy(strategy)
    engine.initialize()

    results = engine.start()
    equity_curve = results.get('equity_curve', [])
    return results, equity_curve


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("Return Permutation Test")
    logger.info("=" * 70)

    config = load_config(args.config)
    logger.info(f"Config: {args.config}")
    logger.info(f"Metric: {args.metric}  |  Permutations: {args.permutations}")
    if args.seed is not None:
        logger.info(f"Random seed: {args.seed}")

    # Step 1: run the real backtest
    logger.info("\nRunning backtest...")
    logging.getLogger('trading_platform').setLevel(logging.WARNING)
    try:
        results, equity_curve = run_backtest(config, logger)
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1
    logging.getLogger('trading_platform').setLevel(logging.INFO)

    if not equity_curve:
        logger.error("Backtest produced no equity curve data.")
        return 1

    logger.info(f"Backtest complete. Equity curve points: {len(equity_curve)}")

    # Step 2: run the permutation test
    logger.info(f"\nRunning {args.permutations} permutations...")
    try:
        test = PermutationTest(
            equity_curve=equity_curve,
            n_permutations=args.permutations,
            metric=args.metric,
            risk_free_rate=args.risk_free_rate,
            random_seed=args.seed,
        )
        result = test.run()
    except Exception as e:
        logger.error(f"Permutation test failed: {e}", exc_info=True)
        return 1

    # Step 3: display results
    print()
    print(PermutationTest.summarize(result))

    # Step 4: optionally save
    if args.output:
        save = {k: v for k, v in result.items() if k != 'null_values'}
        nv = result['null_values']
        save['null_values_summary'] = {
            'min':    float(nv.min()),
            'p5':     float(np.percentile(nv, 5)),
            'median': float(np.percentile(nv, 50)),
            'p95':    float(np.percentile(nv, 95)),
            'max':    float(nv.max()),
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            yaml.dump(save, f, default_flow_style=False)
        logger.info(f"Results saved to: {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
