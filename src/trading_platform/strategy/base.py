"""
Base strategy class that all strategies inherit from.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import logging

from ..core.event import MarketEvent, SignalEvent, FillEvent, OrderEvent
from ..core.event_bus import EventBus
from ..core.types import Symbol
from ..data.manager import DataManager
from ..portfolio.portfolio import Portfolio


logger = logging.getLogger(__name__)


class Strategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    Strategies should implement the abstract methods to define
    their trading logic.
    """
    
    def __init__(self, name: Optional[str] = None):
        """
        Initialize strategy.
        
        Args:
            name: Strategy name (defaults to class name)
        """
        self.name = name or self.__class__.__name__
        self.event_bus: Optional[EventBus] = None
        self.portfolio: Optional[Portfolio] = None
        self.data_manager: Optional[DataManager] = None
        
        self.is_initialized = False
        self.logger = logging.getLogger(f"{__name__}.{self.name}")
        
        self.logger.info(f"Strategy '{self.name}' created")
    
    def initialize(
        self,
        event_bus: EventBus,
        portfolio: Portfolio,
        data_manager: DataManager
    ) -> None:
        """
        Initialize strategy with required components.
        
        Args:
            event_bus: Event bus for communication
            portfolio: Portfolio instance
            data_manager: Data manager instance
        """
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.data_manager = data_manager
        
        # Subscribe to events
        self.event_bus.subscribe(MarketEvent, self.on_market_event)
        self.event_bus.subscribe(FillEvent, self.on_fill_event)
        
        # Call strategy-specific initialization
        self.on_initialize()
        
        self.is_initialized = True
        self.logger.info(f"Strategy '{self.name}' initialized")
    
    @abstractmethod
    def on_initialize(self) -> None:
        """
        Strategy-specific initialization.
        
        Override this to set up indicators, parameters, etc.
        """
        pass
    
    @abstractmethod
    def on_market_event(self, event: MarketEvent) -> None:
        """
        Handle market data events.
        
        Args:
            event: Market data event
        """
        pass
    
    @abstractmethod
    def on_fill_event(self, event: FillEvent) -> None:
        """
        Handle order fill events.
        
        Args:
            event: Fill event
        """
        pass
    
    @abstractmethod
    def get_universe(self) -> List[Symbol]:
        """
        Get the trading universe for this strategy.
        
        Returns:
            List of symbols
        """
        pass
    
    def submit_order(self, order_event: OrderEvent) -> None:
        """
        Submit an order to the execution engine.
        
        Args:
            order_event: Order event to submit
        """
        if not self.is_initialized or self.event_bus is None:
            raise RuntimeError("Strategy not initialized")
        
        self.logger.info(f"Submitting order: {order_event}")
        self.event_bus.publish(order_event)
    
    def get_position(self, symbol: Symbol) -> Optional[int]:
        """
        Get current position quantity for a symbol.
        
        Args:
            symbol: Symbol to query
            
        Returns:
            Position quantity or None
        """
        if self.portfolio is None:
            return None
        
        position = self.portfolio.get_position(symbol)
        return position.quantity if position else None
    
    def get_cash(self) -> float:
        """
        Get available cash.
        
        Returns:
            Available cash
        """
        if self.portfolio is None:
            return 0.0
        return self.portfolio.cash
    
    def __repr__(self) -> str:
        return f"Strategy(name='{self.name}', initialized={self.is_initialized})"
