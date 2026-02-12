"""
Data manager for handling market data operations.

Supports multiple timeframes, asset classes, and data providers.
"""
from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd

from ..core.event_bus import EventBus
from ..core.enums import BarFrequency, AssetClass
from ..core.types import Symbol
from .models import Bar
from .providers.csv_provider import CSVDataProvider
from .providers.yahoo_provider import YahooFinanceProvider


logger = logging.getLogger(__name__)

# Map string frequency to BarFrequency enum and yfinance interval
FREQUENCY_MAP = {
    '1m': (BarFrequency.MINUTE_1, '1m'),
    '5m': (BarFrequency.MINUTE_5, '5m'),
    '15m': (BarFrequency.MINUTE_15, '15m'),
    '30m': (BarFrequency.MINUTE_30, '30m'),
    '1h': (BarFrequency.HOUR_1, '1h'),
    '4h': (BarFrequency.HOUR_4, '4h'),
    '1D': (BarFrequency.DAY_1, '1d'),
    '1W': (BarFrequency.WEEK_1, '1wk'),
    '1M': (BarFrequency.MONTH_1, '1mo'),
}

# Map string asset class to enum
ASSET_CLASS_MAP = {
    'equity': AssetClass.EQUITY,
    'etf': AssetClass.ETF,
    'crypto': AssetClass.CRYPTO,
    'future': AssetClass.FUTURE,
    'fx': AssetClass.FX,
    'option': AssetClass.OPTION,
    'commodity': AssetClass.COMMODITY,
    'bond': AssetClass.BOND,
}


class DataManager:
    """
    Manages market data acquisition, storage, and distribution.

    Supports multiple timeframes and asset classes.
    Data is cached by (symbol, frequency) key.
    """

    def __init__(self, event_bus: EventBus, config: Optional[Dict[str, Any]] = None):
        self.event_bus = event_bus
        self.config = config or {}
        self.providers = {}
        self.subscriptions = {}

        # Data storage keyed by (symbol, frequency_str) or just symbol for backwards compat
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.latest_prices: Dict[str, float] = {}

        # Asset class overrides from config
        self._asset_classes: Dict[str, AssetClass] = {}
        for symbol, ac in self.config.get('asset_classes', {}).items():
            self._asset_classes[symbol] = ASSET_CLASS_MAP.get(ac.lower(), AssetClass.EQUITY)

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
            frequency: Data frequency (1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W, 1M)
        """
        logger.info(f"Loading historical data for {len(symbols)} symbols at {frequency}")

        provider_name = self.config.get('provider', 'yahoo')
        provider = self._create_provider(provider_name)

        # Pass frequency to provider if supported
        if hasattr(provider, 'load_data'):
            import inspect
            sig = inspect.signature(provider.load_data)
            if 'frequency' in sig.parameters:
                data = provider.load_data(symbols, start_date, end_date, frequency=frequency)
            else:
                data = provider.load_data(symbols, start_date, end_date)
        else:
            data = {}

        # Cache with frequency-aware keys for non-daily, plain keys for daily (backwards compat)
        for symbol, df in data.items():
            if frequency != '1D':
                cache_key = f"{symbol}:{frequency}"
            else:
                cache_key = symbol
            self.data_cache[cache_key] = df

        total_bars = sum(len(df) for df in data.values())
        logger.info(
            f"Loaded {total_bars} total bars for {len(data)} symbols "
            f"at {frequency} ({start_date.date()} to {end_date.date()})"
        )

    def _create_provider(self, provider_name: str):
        """Create a data provider instance based on name."""
        if provider_name == 'csv':
            data_dir = self.config.get('csv_data_dir', 'data/historical')
            return CSVDataProvider(data_dir)
        elif provider_name == 'yahoo':
            cache_dir = self.config.get('cache_dir', 'data/cache')
            return YahooFinanceProvider(cache_dir)
        elif provider_name == 'ib':
            from .providers.ib_provider import IBDataProvider
            return IBDataProvider(self.config)
        else:
            raise ValueError(f"Unknown data provider: {provider_name}")

    def get_historical_bars(
        self, symbol: str, frequency: str = '1D'
    ) -> List[Bar]:
        """
        Convert cached DataFrame to list of Bar objects.

        Args:
            symbol: Symbol to retrieve bars for
            frequency: Frequency to retrieve (default: 1D)

        Returns:
            List of Bar objects sorted by timestamp
        """
        # Try frequency-specific key first, fall back to plain symbol
        if frequency != '1D':
            cache_key = f"{symbol}:{frequency}"
        else:
            cache_key = symbol

        df = self.data_cache.get(cache_key)
        if df is None and cache_key != symbol:
            df = self.data_cache.get(symbol)
        if df is None:
            logger.warning(f"No cached data for {symbol} at {frequency}")
            return []

        bar_freq = FREQUENCY_MAP.get(frequency, (BarFrequency.DAY_1, '1d'))[0]
        asset_class = self._asset_classes.get(symbol, AssetClass.EQUITY)

        bars = []
        for timestamp, row in df.iterrows():
            bar = Bar(
                symbol=symbol,
                timestamp=timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp,
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=float(row['Volume']),
                frequency=bar_freq,
                asset_class=asset_class,
            )
            bars.append(bar)

        return bars

    def get_latest_price(self, symbol: Symbol) -> Optional[float]:
        """Get latest price for a symbol."""
        return self.latest_prices.get(symbol)

    def update_latest_price(self, symbol: Symbol, price: float) -> None:
        """Update the latest known price for a symbol."""
        self.latest_prices[symbol] = price

    def get_asset_class(self, symbol: Symbol) -> AssetClass:
        """Get asset class for a symbol."""
        return self._asset_classes.get(symbol, AssetClass.EQUITY)

    def set_asset_class(self, symbol: Symbol, asset_class: AssetClass) -> None:
        """Set asset class for a symbol."""
        self._asset_classes[symbol] = asset_class

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
