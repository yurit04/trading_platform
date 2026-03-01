"""
Interactive Brokers data provider using ib_insync.
"""
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

import pandas as pd

from ...core.types import Symbol

try:
    from ib_insync import IB, Stock, util
    HAS_IB_INSYNC = True
except ImportError:
    HAS_IB_INSYNC = False


logger = logging.getLogger(__name__)


# Mapping from frequency string to IB bar size and duration
_BAR_SIZE_MAP = {
    '1min': ('1 min', '{days} D'),
    '5min': ('5 mins', '{days} D'),
    '15min': ('15 mins', '{days} D'),
    '30min': ('30 mins', '{days} D'),
    '1h': ('1 hour', '{days} D'),
    '1D': ('1 day', '{days} D'),
    '1W': ('1 week', '{days} D'),
    '1M': ('1 month', '{days} D'),
}


class IBDataProvider:
    """
    Fetch historical OHLCV data from Interactive Brokers via ib_insync.

    Connects to TWS/Gateway to request historical bar data.
    Can operate with its own connection or share an existing IB instance.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if not HAS_IB_INSYNC:
            raise ImportError(
                "ib_insync is required for IBDataProvider. "
                "Install it with: pip install ib_insync"
            )

        config = config or {}
        self.host = config.get('ib_host', '127.0.0.1')
        self.port = config.get('ib_port', 7497)
        self.client_id = config.get('ib_data_client_id', config.get('ib_client_id', 2))
        self.timeout = config.get('ib_timeout', 30)
        self.frequency = config.get('ib_bar_size', '1D')

        self._ib: Optional[IB] = None
        self._owns_connection = False

    def _ensure_connected(self) -> None:
        """Connect to IB if not already connected."""
        if self._ib is not None and self._ib.isConnected():
            return

        self._ib = IB()
        self._ib.connect(
            host=self.host,
            port=self.port,
            clientId=self.client_id,
            timeout=self.timeout,
            readonly=True
        )
        self._owns_connection = True
        logger.info(
            f"IBDataProvider connected: host={self.host}, port={self.port}, "
            f"client_id={self.client_id}"
        )

    def disconnect(self) -> None:
        """Disconnect from IB if we own the connection."""
        if self._owns_connection and self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()
            self._ib = None
            self._owns_connection = False
            logger.info("IBDataProvider disconnected")

    def load_data(
        self,
        symbols: List[Symbol],
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, pd.DataFrame]:
        """
        Load historical OHLCV data from Interactive Brokers.

        Args:
            symbols: List of ticker symbols
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dictionary mapping symbol to DataFrame with datetime index
            and columns: Open, High, Low, Close, Volume
        """
        self._ensure_connected()

        data = {}
        for symbol in symbols:
            df = self._download(symbol, start_date, end_date)
            if df is not None and not df.empty:
                data[symbol] = df
            else:
                logger.warning(f"No data loaded for {symbol}")

        logger.info(f"IB provider loaded data for {len(data)}/{len(symbols)} symbols")
        return data

    def _download(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Download historical data from IB for a single symbol."""
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self._ib.qualifyContracts(contract)

            # Calculate duration
            days = (end_date - start_date).days
            if days <= 0:
                logger.warning(f"Invalid date range for {symbol}: {start_date} to {end_date}")
                return None

            # Determine bar size
            bar_size_info = _BAR_SIZE_MAP.get(self.frequency, ('1 day', '{days} D'))
            bar_size = bar_size_info[0]
            duration_str = f"{days} D"

            # For very long durations, IB requires 'Y' format
            if days > 365:
                years = days // 365 + 1
                duration_str = f"{years} Y"

            logger.info(
                f"Requesting IB historical data: {symbol}, "
                f"duration={duration_str}, bar_size={bar_size}"
            )

            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime=end_date.strftime('%Y%m%d %H:%M:%S'),
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1,
                timeout=self.timeout
            )

            if not bars:
                logger.warning(f"IB returned no data for {symbol}")
                return None

            # Convert to DataFrame
            df = util.df(bars)
            df = df.rename(columns={
                'date': 'Date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
            })

            # Set datetime index
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')

            # Keep only OHLCV columns
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

            # Ensure timezone-naive index for consistency
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            df = df.sort_index()

            # Filter to requested date range
            df = df.loc[start_date:end_date]

            logger.info(f"Downloaded {len(df)} bars for {symbol} from IB")
            return df

        except Exception as e:
            logger.error(f"Error downloading {symbol} from IB: {e}")
            return None

    def __del__(self):
        """Ensure disconnection on garbage collection."""
        try:
            self.disconnect()
        except Exception:
            pass
