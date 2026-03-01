"""
CSV data provider for loading historical market data from local files.
"""
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd

from ...core.types import Symbol


logger = logging.getLogger(__name__)


class CSVDataProvider:
    """
    Load historical OHLCV data from CSV files.

    Expected CSV format: Date,Open,High,Low,Close,Volume
    Files should be named {SYMBOL}.csv in the data directory.
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        if not self.data_dir.exists():
            logger.warning(f"Data directory does not exist: {self.data_dir}")

    def load_data(
        self,
        symbols: List[Symbol],
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, pd.DataFrame]:
        """
        Load CSV data for the given symbols and date range.

        Args:
            symbols: List of ticker symbols
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dictionary mapping symbol to DataFrame with datetime index
        """
        data = {}

        for symbol in symbols:
            df = self._load_symbol(symbol, start_date, end_date)
            if df is not None and not df.empty:
                data[symbol] = df
            else:
                logger.warning(f"No data loaded for {symbol}")

        logger.info(f"CSV provider loaded data for {len(data)}/{len(symbols)} symbols")
        return data

    def _load_symbol(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Load a single symbol from CSV."""
        file_path = self.data_dir / f"{symbol}.csv"

        if not file_path.exists():
            logger.warning(f"CSV file not found: {file_path}")
            return None

        try:
            df = pd.read_csv(file_path, parse_dates=True, index_col=0)

            # Normalize column names to title case
            df.columns = [col.strip().title() for col in df.columns]

            # Ensure required columns exist
            required = {'Open', 'High', 'Low', 'Close', 'Volume'}
            if not required.issubset(set(df.columns)):
                logger.warning(
                    f"CSV for {symbol} missing columns. "
                    f"Found: {list(df.columns)}, Required: {required}"
                )
                return None

            # Ensure datetime index
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)

            df.index.name = 'Date'
            df = df.sort_index()

            # Filter to date range
            df = df.loc[start_date:end_date]

            # Keep only OHLCV columns
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

            logger.info(f"Loaded {len(df)} bars for {symbol} from CSV")
            return df

        except Exception as e:
            logger.error(f"Error loading CSV for {symbol}: {e}")
            return None
