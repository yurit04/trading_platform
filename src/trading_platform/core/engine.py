"""
Main trading engine orchestration.
Manages the lifecycle of backtesting and live trading sessions.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging

from .event_bus import EventBus
from .event import Event, MarketEvent, TimerEvent
from .enums import EngineMode
from .exceptions import EngineException, EngineNotInitializedException, EngineAlreadyRunningException
from ..data.manager import DataManager
from ..execution.engine import ExecutionEngine
from ..risk.manager import RiskManager
from ..portfolio.portfolio import Portfolio
from ..strategy.base import Strategy


logger = logging.getLogger(__name__)


class TradingEngine(ABC):
    """
    Base trading engine interface.
    
    Manages coordination between all platform components.
    """
    
    def __init__(
        self,
        initial_capital: float = 1_000_000,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize trading engine.
        
        Args:
            initial_capital: Starting capital
            config: Configuration dictionary
        """
        self.initial_capital = initial_capital
        self.config = config or {}
        
        # Core components
        self.event_bus: Optional[EventBus] = None
        self.data_manager: Optional[DataManager] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.risk_manager: Optional[RiskManager] = None
        self.portfolio: Optional[Portfolio] = None
        
        # Strategies
        self.strategies: List[Strategy] = []
        
        # State
        self.is_running = False
        self.current_time: Optional[datetime] = None
        
        logger.info(f"TradingEngine initialized with capital={initial_capital}")
    
    @abstractmethod
    def initialize(self) -> None:
        """Initialize engine components."""
        pass
    
    @abstractmethod
    def start(self) -> None:
        """Start the trading engine."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the trading engine."""
        pass
    
    def add_strategy(self, strategy: Strategy) -> None:
        """
        Add a strategy to the engine.
        
        Args:
            strategy: Strategy instance to add
        """
        self.strategies.append(strategy)
        logger.info(f"Added strategy: {strategy.__class__.__name__}")
    
    def remove_strategy(self, strategy: Strategy) -> None:
        """
        Remove a strategy from the engine.
        
        Args:
            strategy: Strategy instance to remove
        """
        if strategy in self.strategies:
            self.strategies.remove(strategy)
            logger.info(f"Removed strategy: {strategy.__class__.__name__}")


class BacktestEngine(TradingEngine):
    """
    Backtesting engine for historical simulation.
    
    Processes historical data events sequentially to simulate trading.
    """
    
    def __init__(
        self,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 1_000_000,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize backtest engine.
        
        Args:
            start_date: Backtest start date
            end_date: Backtest end date
            initial_capital: Starting capital
            config: Configuration dictionary
        """
        super().__init__(initial_capital, config)
        self.start_date = start_date
        self.end_date = end_date
        self.mode = EngineMode.BACKTEST
        
        # Backtest-specific state
        self.current_date: Optional[datetime] = None
        self.results: Optional[Dict[str, Any]] = None
        
        logger.info(f"BacktestEngine created: {start_date} to {end_date}")
    
    def initialize(self) -> None:
        """Initialize backtest components."""
        logger.info("Initializing backtest engine...")
        
        # Create event bus in sync mode
        self.event_bus = EventBus(mode='sync')
        
        # Initialize components
        self.data_manager = DataManager(self.event_bus, self.config.get('data', {}))
        self.portfolio = Portfolio(self.initial_capital, self.event_bus)
        self.execution_engine = ExecutionEngine(
            self.event_bus,
            self.portfolio,
            mode='backtest',
            config=self.config.get('execution', {})
        )
        self.risk_manager = RiskManager(
            self.event_bus,
            self.portfolio,
            self.config.get('risk', {})
        )
        
        # Initialize strategies
        for strategy in self.strategies:
            strategy.initialize(
                event_bus=self.event_bus,
                portfolio=self.portfolio,
                data_manager=self.data_manager
            )
        
        self.current_date = self.start_date
        logger.info("Backtest engine initialized successfully")
    
    def start(self) -> Dict[str, Any]:
        """
        Run the backtest.
        
        Returns:
            Dictionary containing backtest results
        """
        if self.is_running:
            raise EngineAlreadyRunningException("Backtest already running")
        
        if self.event_bus is None:
            raise EngineNotInitializedException("Engine not initialized. Call initialize() first")
        
        logger.info("Starting backtest...")
        self.is_running = True
        
        try:
            # Load historical data
            symbols = self._get_all_symbols()
            logger.info(f"Loading data for {len(symbols)} symbols...")
            self.data_manager.load_historical_data(
                symbols=symbols,
                start_date=self.start_date,
                end_date=self.end_date
            )
            
            # Create market events and put in queue
            self._queue_market_events()
            
            # Main event loop
            event_count = 0
            while self.event_bus.has_events() and self.is_running:
                # Get next event
                event = self.event_bus.get()
                if event is None:
                    break
                
                # Update current time
                self.current_time = event.timestamp
                
                # Publish event to subscribers
                self.event_bus.publish(event)
                
                event_count += 1
                if event_count % 10000 == 0:
                    logger.info(f"Processed {event_count} events, date: {self.current_time}")
            
            logger.info(f"Backtest completed. Processed {event_count} events")
            
            # Generate results
            self.results = self._generate_results()
            return self.results
            
        except Exception as e:
            logger.error(f"Backtest failed: {e}", exc_info=True)
            raise EngineException(f"Backtest execution failed") from e
        finally:
            self.is_running = False
    
    def stop(self) -> None:
        """Stop the backtest."""
        logger.info("Stopping backtest...")
        self.is_running = False
    
    def _get_all_symbols(self) -> List[str]:
        """Get all symbols used by strategies."""
        symbols = set()
        for strategy in self.strategies:
            if hasattr(strategy, 'get_universe'):
                symbols.update(strategy.get_universe())
        return list(symbols)
    
    def _queue_market_events(self) -> None:
        """Queue all market events for backtest."""
        # This will be implemented to load data and create events
        # For now, this is a placeholder
        pass
    
    def _generate_results(self) -> Dict[str, Any]:
        """Generate backtest results."""
        if self.portfolio is None:
            return {}
        
        performance = self.portfolio.get_performance_metrics()
        
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'initial_capital': self.initial_capital,
            'final_value': self.portfolio.total_value,
            'total_return': performance.get('total_return', 0),
            'sharpe_ratio': performance.get('sharpe_ratio', 0),
            'max_drawdown': performance.get('max_drawdown', 0),
            'num_trades': performance.get('num_trades', 0),
            'win_rate': performance.get('win_rate', 0),
        }


class LiveTradingEngine(TradingEngine):
    """
    Live trading engine for real-time execution.
    
    Processes live market data and executes orders through brokers.
    """
    
    def __init__(
        self,
        broker: str,
        initial_capital: float = 1_000_000,
        paper_trading: bool = True,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize live trading engine.
        
        Args:
            broker: Broker name
            initial_capital: Starting capital
            paper_trading: Whether to use paper trading mode
            config: Configuration dictionary
        """
        super().__init__(initial_capital, config)
        self.broker = broker
        self.paper_trading = paper_trading
        self.mode = EngineMode.PAPER if paper_trading else EngineMode.LIVE
        
        logger.info(f"LiveTradingEngine created: broker={broker}, paper={paper_trading}")
    
    def initialize(self) -> None:
        """Initialize live trading components."""
        logger.info("Initializing live trading engine...")
        
        # Create event bus in async mode
        self.event_bus = EventBus(mode='async')
        
        # Initialize components
        self.data_manager = DataManager(self.event_bus, self.config.get('data', {}))
        self.portfolio = Portfolio(self.initial_capital, self.event_bus)
        self.execution_engine = ExecutionEngine(
            self.event_bus,
            self.portfolio,
            mode='live',
            broker=self.broker,
            config=self.config.get('execution', {})
        )
        self.risk_manager = RiskManager(
            self.event_bus,
            self.portfolio,
            self.config.get('risk', {})
        )
        
        # Initialize strategies
        for strategy in self.strategies:
            strategy.initialize(
                event_bus=self.event_bus,
                portfolio=self.portfolio,
                data_manager=self.data_manager
            )
        
        logger.info("Live trading engine initialized successfully")
    
    def start(self) -> None:
        """Start live trading."""
        if self.is_running:
            raise EngineAlreadyRunningException("Engine already running")
        
        if self.event_bus is None:
            raise EngineNotInitializedException("Engine not initialized. Call initialize() first")
        
        logger.info("Starting live trading...")
        self.is_running = True
        
        # Subscribe to live data
        symbols = self._get_all_symbols()
        self.data_manager.subscribe_live(symbols)
        
        logger.info("Live trading started successfully")
        # In production, this would run an event loop
        # For now, this is a placeholder
    
    def stop(self) -> None:
        """Stop live trading."""
        logger.info("Stopping live trading...")
        self.is_running = False
        
        # Unsubscribe from data feeds
        if self.data_manager:
            self.data_manager.unsubscribe_all()
        
        logger.info("Live trading stopped")
    
    def _get_all_symbols(self) -> List[str]:
        """Get all symbols used by strategies."""
        symbols = set()
        for strategy in self.strategies:
            if hasattr(strategy, 'get_universe'):
                symbols.update(strategy.get_universe())
        return list(symbols)
