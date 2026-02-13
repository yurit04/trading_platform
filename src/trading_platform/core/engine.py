"""
Main trading engine orchestration.
Manages the lifecycle of backtesting and live trading sessions.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import asyncio
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
        self.portfolio = Portfolio(self.initial_capital, self.event_bus,
                                   start_time=self.start_date)

        # Merge backtest-level execution config with execution section
        execution_config = dict(self.config.get('execution', {}))
        backtest_config = self.config.get('backtest', {})
        for key in ('commission_model', 'commission_rate', 'slippage_model', 'slippage_bps'):
            if key in backtest_config and key not in execution_config:
                execution_config[key] = backtest_config[key]

        self.risk_manager = RiskManager(
            self.event_bus,
            self.portfolio,
            self.config.get('risk', {})
        )
        self.execution_engine = ExecutionEngine(
            self.event_bus,
            self.portfolio,
            mode='backtest',
            config=execution_config,
            risk_manager=self.risk_manager
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

        # Add risk metrics
        if self.risk_manager is not None:
            results['risk_metrics'] = self.risk_manager.calculate_portfolio_risk()

        # Attach raw data for report generation
        results['equity_curve'] = self.portfolio.equity_curve
        results['trade_history'] = self.portfolio.trade_history
        results['positions'] = dict(self.portfolio.positions)

        return results


class LiveTradingEngine(TradingEngine):
    """
    Live trading engine for real-time execution.

    Features:
    - Async event loop for real-time processing
    - Automatic reconnection on broker/data disconnects
    - Periodic health monitoring and status reporting
    - Graceful shutdown with position reconciliation
    - Order state tracking and reconciliation
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

        # Live-specific config
        live_config = self.config.get('live', {})
        self.health_interval = live_config.get('health_interval_seconds', 60)
        self.max_reconnect_attempts = live_config.get('max_reconnect_attempts', 5)
        self.reconnect_delay = live_config.get('reconnect_delay_seconds', 5)

        # State tracking
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._health_task = None
        self._data_task = None
        self._reconnect_count = 0
        self._last_market_event_time: Optional[datetime] = None
        self._start_time: Optional[datetime] = None
        self._event_count = 0
        self._error_count = 0

        logger.info(f"LiveTradingEngine created: broker={broker}, paper={paper_trading}")

    def initialize(self) -> None:
        """Initialize live trading components."""
        logger.info("Initializing live trading engine...")

        # Create event bus in async mode
        self.event_bus = EventBus(mode='async')

        # Initialize components
        self.data_manager = DataManager(self.event_bus, self.config.get('data', {}))
        self.portfolio = Portfolio(self.initial_capital, self.event_bus)
        self.risk_manager = RiskManager(
            self.event_bus,
            self.portfolio,
            self.config.get('risk', {})
        )
        self.execution_engine = ExecutionEngine(
            self.event_bus,
            self.portfolio,
            mode='live',
            broker=self.broker,
            config=self.config.get('execution', {}),
            risk_manager=self.risk_manager
        )

        # Subscribe to market events for tracking
        self.event_bus.subscribe(MarketEvent, self._on_market_event)

        # Initialize strategies
        for strategy in self.strategies:
            strategy.initialize(
                event_bus=self.event_bus,
                portfolio=self.portfolio,
                data_manager=self.data_manager
            )

        logger.info("Live trading engine initialized successfully")

    def start(self) -> None:
        """
        Start live trading with async event loop.

        Blocks until stop() is called or a fatal error occurs.
        """
        if self.is_running:
            raise EngineAlreadyRunningException("Engine already running")

        if self.event_bus is None:
            raise EngineNotInitializedException("Engine not initialized. Call initialize() first")

        logger.info("Starting live trading...")
        self.is_running = True
        self._start_time = datetime.now()

        # Subscribe to live data
        symbols = self._get_all_symbols()
        self.data_manager.subscribe_live(symbols, callback=self._handle_live_data)

        # Start async event loop
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_async())
        except Exception as e:
            logger.error(f"Event loop error: {e}", exc_info=True)
            raise
        finally:
            if self._loop and not self._loop.is_closed():
                self._loop.close()

    async def _run_async(self) -> None:
        """Main async event loop."""
        self._shutdown_event = asyncio.Event()

        # Start background tasks
        self._health_task = asyncio.create_task(self._health_monitor())

        logger.info("Live trading event loop running")

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Cancel background tasks
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        logger.info("Event loop shutdown complete")

    def _handle_live_data(self, symbol: str, bar_data: dict) -> None:
        """
        Callback for live data feed updates.

        Converts raw data to MarketEvent and publishes to event bus.
        """
        try:
            from .event import MarketEvent
            from .enums import EventType

            event = MarketEvent(
                timestamp=bar_data.get('timestamp', datetime.now()),
                event_type=EventType.MARKET,
                symbol=symbol,
                open=bar_data['open'],
                high=bar_data['high'],
                low=bar_data['low'],
                close=bar_data['close'],
                volume=bar_data.get('volume', 0)
            )

            # Update execution engine with latest bar
            from ..data.models import Bar
            bar = Bar(
                timestamp=event.timestamp,
                symbol=symbol,
                open=event.open,
                high=event.high,
                low=event.low,
                close=event.close,
                volume=event.volume
            )
            self.execution_engine.update_market_data(symbol, bar)
            self.data_manager.update_latest_price(symbol, event.close)
            self.portfolio.update_prices({symbol: event.close})

            self.event_bus.publish(event)
            self._event_count += 1

        except Exception as e:
            self._error_count += 1
            logger.error(f"Error processing live data for {symbol}: {e}", exc_info=True)

    def _on_market_event(self, event: MarketEvent) -> None:
        """Track last market event time for health monitoring."""
        self._last_market_event_time = datetime.now()

    async def _health_monitor(self) -> None:
        """Periodic health check and status reporting."""
        while self.is_running:
            try:
                await asyncio.sleep(self.health_interval)

                if not self.is_running:
                    break

                now = datetime.now()
                uptime = now - self._start_time if self._start_time else timedelta()

                # Check data staleness
                data_stale = False
                if self._last_market_event_time:
                    data_age = (now - self._last_market_event_time).total_seconds()
                    if data_age > self.health_interval * 3:
                        data_stale = True
                        logger.warning(
                            f"HEALTH: Market data stale — last event {data_age:.0f}s ago"
                        )

                # Log status
                portfolio_value = self.portfolio.total_value if self.portfolio else 0
                num_positions = len([p for p in self.portfolio.positions.values()
                                     if p.quantity != 0]) if self.portfolio else 0

                logger.info(
                    f"HEALTH: uptime={uptime}, events={self._event_count}, "
                    f"errors={self._error_count}, portfolio=${portfolio_value:,.2f}, "
                    f"positions={num_positions}, data_stale={data_stale}"
                )

                # Attempt reconnection if data is stale
                if data_stale and self._reconnect_count < self.max_reconnect_attempts:
                    await self._attempt_reconnect()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}", exc_info=True)

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect data feeds."""
        self._reconnect_count += 1
        logger.warning(
            f"Attempting reconnection ({self._reconnect_count}/{self.max_reconnect_attempts})..."
        )

        try:
            # Unsubscribe and resubscribe
            if self.data_manager:
                self.data_manager.unsubscribe_all()
                await asyncio.sleep(self.reconnect_delay)
                symbols = self._get_all_symbols()
                self.data_manager.subscribe_live(symbols, callback=self._handle_live_data)
                logger.info("Reconnection successful")
                self._reconnect_count = 0  # Reset on success
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            if self._reconnect_count >= self.max_reconnect_attempts:
                logger.critical(
                    f"Max reconnection attempts ({self.max_reconnect_attempts}) reached. "
                    f"Stopping engine."
                )
                self.stop()

    def stop(self) -> None:
        """Graceful shutdown of live trading."""
        if not self.is_running:
            return

        logger.info("Stopping live trading...")
        self.is_running = False

        # Log final state
        if self.portfolio:
            logger.info(f"Final portfolio value: ${self.portfolio.total_value:,.2f}")
            logger.info(f"Cash: ${self.portfolio.cash:,.2f}")
            open_positions = {s: p for s, p in self.portfolio.positions.items()
                             if p.quantity != 0}
            if open_positions:
                logger.info(f"Open positions ({len(open_positions)}):")
                for symbol, pos in open_positions.items():
                    logger.info(
                        f"  {symbol}: {pos.quantity} shares @ "
                        f"${pos.average_price:.2f} (unrealized: ${pos.unrealized_pnl:,.2f})"
                    )

        if self.risk_manager:
            risk_metrics = self.risk_manager.calculate_portfolio_risk()
            logger.info(f"Final risk metrics: {risk_metrics}")

        # Disconnect data feeds
        if self.data_manager:
            self.data_manager.unsubscribe_all()

        # Disconnect broker
        if self.execution_engine and hasattr(self.execution_engine.broker, 'disconnect'):
            try:
                self.execution_engine.broker.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting broker: {e}")

        # Signal async loop to stop
        if self._shutdown_event:
            self._shutdown_event.set()

        uptime = datetime.now() - self._start_time if self._start_time else timedelta()
        logger.info(
            f"Live trading stopped. Uptime: {uptime}, "
            f"Events: {self._event_count}, Errors: {self._error_count}"
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status for monitoring."""
        now = datetime.now()
        return {
            'is_running': self.is_running,
            'mode': self.mode.name,
            'broker': self.broker,
            'uptime_seconds': (now - self._start_time).total_seconds() if self._start_time else 0,
            'event_count': self._event_count,
            'error_count': self._error_count,
            'reconnect_count': self._reconnect_count,
            'portfolio_value': self.portfolio.total_value if self.portfolio else 0,
            'cash': self.portfolio.cash if self.portfolio else 0,
            'num_positions': len([p for p in self.portfolio.positions.values()
                                  if p.quantity != 0]) if self.portfolio else 0,
            'last_market_event': self._last_market_event_time.isoformat() if self._last_market_event_time else None,
        }

    def _get_all_symbols(self) -> List[str]:
        """Get all symbols used by strategies."""
        symbols = set()
        for strategy in self.strategies:
            if hasattr(strategy, 'get_universe'):
                symbols.update(strategy.get_universe())
        return list(symbols)
