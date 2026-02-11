#!/usr/bin/env python
"""
Download historical market data for backtesting.

Usage:
    python scripts/download_data.py --config config/strategies/momentum.yaml
    python scripts/download_data.py --symbols AAPL MSFT GOOGL --start 2020-01-01 --end 2023-12-31
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

from trading_platform.data.providers.yahoo_provider import YahooFinanceProvider
from trading_platform.utils.logging import setup_logging


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Download historical market data')

    parser.add_argument(
        '--config',
        type=str,
        help='Path to strategy configuration file (reads symbols and dates from it)'
    )

    parser.add_argument(
        '--symbols',
        nargs='+',
        type=str,
        help='Symbols to download (e.g. AAPL MSFT GOOGL)'
    )

    parser.add_argument(
        '--start',
        type=str,
        default='2020-01-01',
        help='Start date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--end',
        type=str,
        default='2023-12-31',
        help='End date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='data/cache',
        help='Output directory for cached data (default: data/cache)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    return parser.parse_args()


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

    # Determine symbols and dates
    if args.config:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)

        symbols = config.get('universe', {}).get('symbols', [])
        backtest = config.get('backtest', {})
        start_str = backtest.get('start_date', args.start)
        end_str = backtest.get('end_date', args.end)
    elif args.symbols:
        symbols = args.symbols
        start_str = args.start
        end_str = args.end
    else:
        logger.error("Provide either --config or --symbols")
        return 1

    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_str, '%Y-%m-%d')

    logger.info(f"Downloading data for {len(symbols)} symbols: {symbols}")
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")
    logger.info(f"Output directory: {args.output}")

    provider = YahooFinanceProvider(cache_dir=args.output)
    data = provider.load_data(symbols, start_date, end_date)

    logger.info("=" * 60)
    logger.info("Download Summary")
    logger.info("=" * 60)
    for symbol, df in sorted(data.items()):
        logger.info(f"  {symbol}: {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")

    failed = set(symbols) - set(data.keys())
    if failed:
        logger.warning(f"  Failed: {failed}")

    logger.info(f"Total: {sum(len(df) for df in data.values())} bars for {len(data)} symbols")
    return 0


if __name__ == '__main__':
    sys.exit(main())
