"""
Data manager for handling market data operations.
"""
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd

from ..core.event_bus import EventBus
from ..core.types import Symbol
from .models import Bar
from .providers.csv_provider import CSVDataProvider
from .providers.yahoo_provider import YahooFinanceProvider


logger = logging.getLogger(__name__)


class DataManager:
    """
    Manages market data acquisition, storage, and distribution.

    Coordinates between various data providers and the event bus.
    """

    def __init__(self, event_bus: EventBus, config: Optional[Dict[str, Any]] = None):
        """
        Initialize data manager.

        Args:
            event_bus: Event bus for publishing data
            config: Configuration dictionary
        """
        self.event_bus = event_bus
        self.config = config or {}
        self.providers = {}
        self.subscriptions = {}

        # Data storage
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.latest_prices: Dict[str, float] = {}

        logger.info("DataManager initialized")

    def load_historical_data(
        self,
        symbols: List[Symbol],
        start_date: datetime,
        end_date: datetime,
        frequency: str = '1D'
    ) -> None:
        """
        Load historical data for backtesting.

        Args:
            symbols: List of symbols to load
            start_date: Start date
            end_date: End date
            frequency: Data frequency
        """
        logger.info(f"Loading historical data for {len(symbols)} symbols")

        provider_name = self.config.get('provider', 'yahoo')
        provider = self._create_provider(provider_name)

        data = provider.load_data(symbols, start_date, end_date)
        self.data_cache.update(data)

        total_bars = sum(len(df) for df in data.values())
        logger.info(
            f"Loaded {total_bars} total bars for {len(data)} symbols "
            f"({start_date.date()} to {end_date.date()})"
        )

    def _create_provider(self, provider_name: str):
        """Create a data provider instance based on name."""
        if provider_name == 'csv':
            data_dir = self.config.get('csv_data_dir', 'data/historical')
            return CSVDataProvider(data_dir)
        elif provider_name == 'yahoo':
            cache_dir = self.config.get('cache_dir', 'data/cache')
            return YahooFinanceProvider(cache_dir)
        else:
            raise ValueError(f"Unknown data provider: {provider_name}")

    def get_historical_bars(self, symbol: str) -> List[Bar]:
        """
        Convert cached DataFrame to list of Bar objects.

        Args:
            symbol: Symbol to retrieve bars for

        Returns:
            List of Bar objects sorted by timestamp
        """
        df = self.data_cache.get(symbol)
        if df is None:
            logger.warning(f"No cached data for {symbol}")
            return []

        bars = []
        for timestamp, row in df.iterrows():
            bar = Bar(
                symbol=symbol,
                timestamp=timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp,
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=float(row['Volume'])
            )
            bars.append(bar)

        return bars

    def get_latest_price(self, symbol: Symbol) -> Optional[float]:
        """
        Get latest price for a symbol.

        Args:
            symbol: Symbol to query

        Returns:
            Latest price or None
        """
        return self.latest_prices.get(symbol)

    def update_latest_price(self, symbol: Symbol, price: float) -> None:
        """
        Update the latest known price for a symbol.

        Args:
            symbol: Symbol to update
            price: Latest price
        """
        self.latest_prices[symbol] = price

    def subscribe_live(self, symbols: List[Symbol], callback: Optional[Callable] = None) -> None:
        """
        Subscribe to live data feeds.

        Args:
            symbols: List of symbols to subscribe to
            callback: Optional callback for data updates
        """
        logger.info(f"Subscribing to live data for {len(symbols)} symbols")
        for symbol in symbols:
            self.subscriptions[symbol] = callback

    def unsubscribe_all(self) -> None:
        """Unsubscribe from all data feeds."""
        logger.info("Unsubscribing from all data feeds")
        self.subscriptions.clear()
