"""
Yahoo Finance data provider using yfinance.

Supports daily and intraday frequencies.
"""
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd
import yfinance as yf

from ...core.types import Symbol


logger = logging.getLogger(__name__)

# yfinance interval strings
VALID_INTERVALS = {
    '1m', '2m', '5m', '15m', '30m', '60m', '90m',
    '1h', '1d', '5d', '1wk', '1mo', '3mo',
}

# Map our frequency strings to yfinance intervals
FREQ_TO_YF = {
    '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
    '1h': '1h', '4h': '60m',  # yfinance doesn't have 4h, use 1h
    '1D': '1d', '1W': '1wk', '1M': '1mo',
}


class YahooFinanceProvider:
    """
    Fetch historical OHLCV data from Yahoo Finance.

    Caches downloaded data as parquet files to avoid repeated API calls.
    Supports daily and intraday timeframes.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_data(
        self,
        symbols: List[Symbol],
        start_date: datetime,
        end_date: datetime,
        frequency: str = '1D'
    ) -> Dict[str, pd.DataFrame]:
        """
        Load data for the given symbols, date range, and frequency.

        Args:
            symbols: List of ticker symbols
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            frequency: Data frequency (1m, 5m, 15m, 30m, 1h, 1D, 1W, 1M)

        Returns:
            Dictionary mapping symbol to DataFrame with datetime index
        """
        data = {}
        yf_interval = FREQ_TO_YF.get(frequency, '1d')

        for symbol in symbols:
            # Try cache first
            df = self._load_from_cache(symbol, start_date, end_date, frequency)

            if df is None:
                df = self._download(symbol, start_date, end_date, yf_interval)
                if df is not None and not df.empty:
                    self._save_to_cache(symbol, start_date, end_date, df, frequency)

            if df is not None and not df.empty:
                data[symbol] = df
            else:
                logger.warning(f"No data loaded for {symbol}")

        logger.info(f"Yahoo provider loaded data for {len(data)}/{len(symbols)} symbols at {frequency}")
        return data

    def _download(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = '1d'
    ) -> Optional[pd.DataFrame]:
        """Download data from Yahoo Finance for a single symbol."""
        try:
            logger.info(f"Downloading {symbol} from Yahoo Finance (interval={interval})...")
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                interval=interval,
                auto_adjust=True
            )

            if df.empty:
                logger.warning(f"Yahoo Finance returned no data for {symbol}")
                return None

            # Keep only OHLCV columns
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

            # Ensure timezone-naive index for consistency
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            df.index.name = 'Date'
            df = df.sort_index()

            logger.info(f"Downloaded {len(df)} bars for {symbol} (interval={interval})")
            return df

        except Exception as e:
            logger.error(f"Error downloading {symbol} from Yahoo Finance: {e}")
            return None

    def _cache_path(
        self, symbol: str, start_date: datetime, end_date: datetime,
        frequency: str = '1D'
    ) -> Optional[Path]:
        """Get cache file path for a symbol and date range."""
        if self.cache_dir is None:
            return None
        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')
        freq_str = frequency.replace('/', '')
        return self.cache_dir / f"{symbol}_{start_str}_{end_str}_{freq_str}.parquet"

    def _load_from_cache(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        frequency: str = '1D'
    ) -> Optional[pd.DataFrame]:
        """Load data from parquet cache if available."""
        path = self._cache_path(symbol, start_date, end_date, frequency)
        if path is None or not path.exists():
            # Fall back to legacy cache path (without frequency)
            legacy_path = self._legacy_cache_path(symbol, start_date, end_date)
            if legacy_path and legacy_path.exists() and frequency == '1D':
                path = legacy_path
            else:
                return None

        try:
            df = pd.read_parquet(path)
            logger.info(f"Loaded {len(df)} bars for {symbol} from cache")
            return df
        except Exception as e:
            logger.warning(f"Failed to read cache for {symbol}: {e}")
            return None

    def _legacy_cache_path(
        self, symbol: str, start_date: datetime, end_date: datetime
    ) -> Optional[Path]:
        """Legacy cache path without frequency (for backwards compatibility)."""
        if self.cache_dir is None:
            return None
        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')
        return self.cache_dir / f"{symbol}_{start_str}_{end_str}.parquet"

    def _save_to_cache(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        df: pd.DataFrame,
        frequency: str = '1D'
    ) -> None:
        """Save data to parquet cache."""
        path = self._cache_path(symbol, start_date, end_date, frequency)
        if path is None:
            return

        try:
            df.to_parquet(path)
            logger.debug(f"Cached {symbol} data to {path}")
        except Exception as e:
            logger.warning(f"Failed to cache data for {symbol}: {e}")
