#!/usr/bin/env python
"""
Backtest execution script.

Usage:
    python scripts/backtest.py --config config/strategies/momentum.yaml
    python scripts/backtest.py --strategy momentum --start 2020-01-01 --end 2023-12-31
    python scripts/backtest.py --config config/strategies/momentum.yaml --no-report
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime
import yaml
import logging

# Add project root and src to path
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)
sys.path.insert(0, str(Path(project_root) / 'src'))

from trading_platform.core.engine import BacktestEngine
from trading_platform.analytics.report import ReportGenerator
from trading_platform.utils.logging import setup_logging


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run backtests')

    parser.add_argument(
        '--config',
        type=str,
        help='Path to strategy configuration file'
    )

    parser.add_argument(
        '--strategy',
        type=str,
        help='Strategy name (if not using config file)'
    )

    parser.add_argument(
        '--start',
        type=str,
        help='Start date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--end',
        type=str,
        help='End date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--capital',
        type=float,
        default=1_000_000,
        help='Initial capital (default: 1,000,000)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='results/backtests',
        help='Output directory for results'
    )

    parser.add_argument(
        '--no-report',
        action='store_true',
        help='Skip report generation (for fast iteration)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    return parser.parse_args()


def display_results(results: dict, logger: logging.Logger) -> None:
    """Display expanded metrics to console."""
    logger.info("=" * 70)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 70)
    logger.info(f"  Initial Capital:     ${results['initial_capital']:>14,.2f}")
    logger.info(f"  Final Value:         ${results['final_value']:>14,.2f}")
    logger.info("")
    logger.info("  RETURN METRICS")
    logger.info(f"  Total Return:        {results.get('total_return', 0):>10.2%}")
    logger.info(f"  CAGR:                {results.get('cagr', 0):>10.2%}")
    logger.info(f"  Volatility (ann.):   {results.get('volatility', 0):>10.2%}")
    logger.info("")
    logger.info("  RISK METRICS")
    logger.info(f"  Sharpe Ratio:        {results.get('sharpe_ratio', 0):>10.2f}")
    logger.info(f"  Sortino Ratio:       {results.get('sortino_ratio', 0):>10.2f}")
    logger.info(f"  Max Drawdown:        {results.get('max_drawdown', 0):>10.2%}")
    logger.info(f"  Calmar Ratio:        {results.get('calmar_ratio', 0):>10.2f}")
    logger.info("")
    logger.info("  TRADE METRICS")
    logger.info(f"  Total Trades:        {results.get('num_trades', 0):>10d}")
    logger.info(f"  Win Rate:            {results.get('win_rate', 0):>10.2%}")
    pf = results.get('profit_factor', 0)
    pf_str = f'{pf:>10.2f}' if pf != float('inf') else '       inf'
    logger.info(f"  Profit Factor:       {pf_str}")
    logger.info(f"  Avg Win:             ${results.get('avg_win', 0):>13,.2f}")
    logger.info(f"  Avg Loss:            ${results.get('avg_loss', 0):>13,.2f}")
    logger.info(f"  Max Consec. Wins:    {results.get('max_consecutive_wins', 0):>10d}")
    logger.info(f"  Max Consec. Losses:  {results.get('max_consecutive_losses', 0):>10d}")
    logger.info(f"  Avg Trade Duration:  {results.get('avg_trade_duration_days', 0):>10.1f} days")
    logger.info("=" * 70)


def main():
    """Main backtest execution function."""
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

    logger.info("=" * 80)
    logger.info("Starting Backtest")
    logger.info("=" * 80)

    # Load configuration
    if args.config:
        config = load_config(args.config)
        logger.info(f"Loaded configuration from: {args.config}")
    else:
        config = {}
        logger.info("Using command line parameters")

    # Parse dates
    start_date = datetime.strptime(
        args.start or config.get('backtest', {}).get('start_date', '2020-01-01'),
        '%Y-%m-%d'
    )
    end_date = datetime.strptime(
        args.end or config.get('backtest', {}).get('end_date', '2023-12-31'),
        '%Y-%m-%d'
    )

    initial_capital = args.capital or config.get('backtest', {}).get('initial_capital', 1_000_000)

    logger.info(f"Backtest Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Initial Capital: ${initial_capital:,.2f}")

    # Create backtest engine
    engine = BacktestEngine(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        config=config
    )

    # Load strategy
    strategy_class_path = config.get('strategy', {}).get('class')
    if strategy_class_path:
        # Import strategy dynamically
        module_path, class_name = strategy_class_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        strategy_class = getattr(module, class_name)

        # Create strategy instance
        strategy_params = config.get('parameters', {})
        universe_config = config.get('universe', {})

        strategy = strategy_class(
            universe=universe_config.get('symbols', []),
            **strategy_params
        )

        engine.add_strategy(strategy)
        logger.info(f"Loaded strategy: {strategy_class.__name__}")
    else:
        logger.error("No strategy specified in configuration")
        return 1

    # Initialize engine
    logger.info("Initializing backtest engine...")
    engine.initialize()

    # Run backtest
    logger.info("Running backtest...")
    try:
        results = engine.start()

        # Display expanded results
        display_results(results, logger)

        # Extract raw data (not serializable to YAML)
        equity_curve = results.pop('equity_curve', [])
        trade_history = results.pop('trade_history', [])
        positions = results.pop('positions', {})

        if not args.no_report:
            # Generate full report suite
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = str(Path(args.output) / f'backtest_{timestamp}')

            logger.info(f"Generating reports in {output_dir}...")
            ReportGenerator.generate_full_report(
                results=results,
                equity_curve=equity_curve,
                trade_history=trade_history,
                positions=positions,
                output_dir=output_dir
            )
            logger.info(f"Reports saved to: {output_dir}")
        else:
            # Just save YAML results
            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"backtest_{timestamp}.yaml"

            yaml_results = {}
            for k, v in results.items():
                if isinstance(v, datetime):
                    yaml_results[k] = v.strftime('%Y-%m-%d')
                elif isinstance(v, float) and v == float('inf'):
                    yaml_results[k] = 'inf'
                else:
                    yaml_results[k] = v

            with open(output_file, 'w') as f:
                yaml.dump(yaml_results, f)
            logger.info(f"Results saved to: {output_file}")

        return 0

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
