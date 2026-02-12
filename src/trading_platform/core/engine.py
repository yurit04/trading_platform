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
from .enums import EngineMode, EventType
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
        self.strategies.append(strategy)
        logger.info(f"Added strategy: {strategy.__class__.__name__}")

    def remove_strategy(self, strategy: Strategy) -> None:
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

        # Merge backtest-level execution config with execution section
        execution_config = dict(self.config.get('execution', {}))
        backtest_config = self.config.get('backtest', {})
        for key in ('commission_model', 'commission_rate', 'slippage_model', 'slippage_bps'):
            if key in backtest_config and key not in execution_config:
                execution_config[key] = backtest_config[key]

        self.execution_engine = ExecutionEngine(
            self.event_bus,
            self.portfolio,
            mode='backtest',
            config=execution_config
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
                event = self.event_bus.get(block=False)
                if event is None:
                    break

                # Update current time
                self.current_time = event.timestamp

                # If market event, update components with latest data
                if isinstance(event, MarketEvent):
                    bar_from_event = self._market_event_to_bar(event)
                    self.execution_engine.update_market_data(event.symbol, bar_from_event)
                    self.data_manager.update_latest_price(event.symbol, event.close)
                    self.portfolio.update_prices({event.symbol: event.close})

                # Publish event to subscribers (strategies, execution, etc.)
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
        """Queue all market events for the backtest in chronological order."""
        logger.info("Queueing market events for backtest...")

        symbols = self._get_all_symbols()
        total_events = 0

        for symbol in symbols:
            bars = self.data_manager.get_historical_bars(symbol)
            for bar in bars:
                event = MarketEvent(
                    timestamp=bar.timestamp,
                    event_type=EventType.MARKET,
                    symbol=bar.symbol,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume
                )
                self.event_bus.put(event)
                total_events += 1

        logger.info(f"Queued {total_events} market events for {len(symbols)} symbols")

    @staticmethod
    def _market_event_to_bar(event: MarketEvent):
        """Convert a MarketEvent back to a Bar for the execution engine."""
        from ..data.models import Bar
        return Bar(
            timestamp=event.timestamp,
            symbol=event.symbol,
            open=event.open,
            high=event.high,
            low=event.low,
            close=event.close,
            volume=event.volume
        )

    def _generate_results(self) -> Dict[str, Any]:
        """Generate backtest results including all metrics and raw data."""
        if self.portfolio is None:
            return {}

        performance = self.portfolio.get_performance_metrics()

        results = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'initial_capital': self.initial_capital,
            'final_value': self.portfolio.total_value,
        }
        # Merge all expanded metrics
        results.update(performance)

        # Attach raw data for report generation
        results['equity_curve'] = self.portfolio.equity_curve
        results['trade_history'] = self.portfolio.trade_history
        results['positions'] = dict(self.portfolio.positions)

        return results


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

    def stop(self) -> None:
        """Stop live trading."""
        logger.info("Stopping live trading...")
        self.is_running = False

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
