from .csv_provider import CSVDataProvider
from .kraken_provider import KrakenDataProvider
from .kraken_ws_feed import KrakenWebSocketFeed

try:
    from .yahoo_provider import YahooFinanceProvider
except ImportError:
    YahooFinanceProvider = None  # type: ignore[assignment,misc]

try:
    from .ib_provider import IBDataProvider
except ImportError:
    IBDataProvider = None  # type: ignore[assignment,misc]

__all__ = [
    'CSVDataProvider',
    'YahooFinanceProvider',
    'IBDataProvider',
    'KrakenDataProvider',
    'KrakenWebSocketFeed',
]
