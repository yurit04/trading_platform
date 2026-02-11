#!/usr/bin/env python
"""
Live trading execution script.

Usage:
    python scripts/live_trade.py --config config/strategies/momentum.yaml --broker ib
    python scripts/live_trade.py --config config/strategies/momentum.yaml --broker ib --paper
    python scripts/live_trade.py --config config/strategies/momentum.yaml --broker ib --mode paper
"""
import argparse
import signal
import sys
import time
from pathlib import Path
from datetime import datetime
import yaml
import logging

# Add project root and src to path
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)
sys.path.insert(0, str(Path(project_root) / 'src'))

from trading_platform.core.engine import LiveTradingEngine
from trading_platform.utils.logging import setup_logging


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Run live trading')

    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='Path to strategy configuration file'
    )

    parser.add_argument(
        '--broker',
        type=str,
        required=True,
        choices=['ib', 'binance', 'coinbase', 'kraken', 'simulated'],
        help='Broker to use for execution'
    )

    parser.add_argument(
        '--mode',
        type=str,
        default='paper',
        choices=['paper', 'live'],
        help='Trading mode (default: paper)'
    )

    parser.add_argument(
        '--paper',
        action='store_true',
        help='Shorthand for --mode paper'
    )

    parser.add_argument(
        '--capital',
        type=float,
        default=None,
        help='Initial capital (overrides config value)'
    )

    parser.add_argument(
        '--log-file',
        type=str,
        default=None,
        help='Log file path (default: logs/live_<timestamp>.log)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    return parser.parse_args()


def load_strategy(config: dict):
    """
    Dynamically load a strategy class from configuration.

    Args:
        config: Strategy configuration dictionary

    Returns:
        Instantiated strategy object
    """
    strategy_class_path = config.get('strategy', {}).get('class')
    if not strategy_class_path:
        raise ValueError("No strategy class specified in configuration ('strategy.class')")

    module_path, class_name = strategy_class_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)

    strategy_params = config.get('parameters', {})
    universe_config = config.get('universe', {})

    strategy = strategy_class(
        universe=universe_config.get('symbols', []),
        **strategy_params
    )

    return strategy


def main():
    """Main live trading execution function."""
    args = parse_args()

    # Resolve trading mode
    paper_trading = args.paper or args.mode == 'paper'
    mode_label = 'PAPER' if paper_trading else 'LIVE'

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = args.log_file or f'logs/live_{mode_label.lower()}_{timestamp}.log'
    setup_logging(level=log_level, log_file=log_file)
    logger = logging.getLogger(__name__)

    logger.info("=" * 80)
    logger.info(f"Starting {mode_label} Trading")
    logger.info("=" * 80)

    # Load configuration
    config = load_config(args.config)
    logger.info(f"Loaded configuration from: {args.config}")

    # Resolve capital
    initial_capital = (
        args.capital
        or config.get('live', {}).get('initial_capital')
        or config.get('backtest', {}).get('initial_capital', 1_000_000)
    )

    logger.info(f"Mode:            {mode_label}")
    logger.info(f"Broker:          {args.broker}")
    logger.info(f"Initial Capital: ${initial_capital:,.2f}")

    # Safety confirmation for live mode
    if not paper_trading:
        logger.warning("*** LIVE TRADING MODE - REAL MONEY AT RISK ***")
        confirmation = input("Type 'CONFIRM LIVE' to proceed with live trading: ")
        if confirmation.strip() != 'CONFIRM LIVE':
            logger.info("Live trading cancelled by user.")
            return 0

    # Create live trading engine
    engine = LiveTradingEngine(
        broker=args.broker,
        initial_capital=initial_capital,
        paper_trading=paper_trading,
        config=config
    )

    # Load strategy
    strategy = load_strategy(config)
    engine.add_strategy(strategy)
    logger.info(f"Loaded strategy: {strategy.__class__.__name__}")

    # Register shutdown handler for graceful stop
    def shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, shutting down gracefully...")
        engine.stop()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Initialize engine
    logger.info("Initializing live trading engine...")
    engine.initialize()

    # Start trading
    logger.info("Starting event loop...")
    try:
        engine.start()

        # Keep the process alive while the engine is running
        while engine.is_running:
            time.sleep(1)

    except Exception as e:
        logger.error(f"Live trading error: {e}", exc_info=True)
        return 1
    finally:
        engine.stop()
        logger.info("=" * 80)
        logger.info(f"{mode_label} Trading Session Ended")
        logger.info("=" * 80)

    return 0


if __name__ == '__main__':
    sys.exit(main())
