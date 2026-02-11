"""
Data manager for handling market data operations.
"""
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
import logging

from ..core.event_bus import EventBus
from ..core.types import Symbol


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
        # Implementation will load data from providers
        pass
    
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
    
    def get_latest_price(self, symbol: Symbol) -> Optional[float]:
        """
        Get latest price for a symbol.
        
        Args:
            symbol: Symbol to query
            
        Returns:
            Latest price or None
        """
        # Implementation will query latest data
        return None
