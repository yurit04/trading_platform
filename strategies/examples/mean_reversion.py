"""
Example mean reversion trading strategy.
"""
from typing import List, Optional
from collections import deque
from datetime import datetime
import logging
import math

from trading_platform.strategy.base import Strategy
from trading_platform.core.event import MarketEvent, FillEvent, OrderEvent
from trading_platform.core.enums import OrderType, OrderSide, EventType
from trading_platform.core.types import Symbol


logger = logging.getLogger(__name__)


class MeanReversionStrategy(Strategy):
    """
    Mean reversion strategy that buys oversold securities and sells when they revert to the mean.

    Strategy Logic:
    1. Calculate z-score: (price - SMA) / rolling_std over lookback_period
    2. When z-score < -entry_threshold: BUY (oversold)
    3. When z-score > exit_threshold and holding: SELL (reverted to mean)
    4. When z-score > entry_threshold: skip (overbought, don't buy)
    5. Max positions limited by max_positions parameter
    6. Position sizing: equal weight (portfolio_value / max_positions)
    """

    def __init__(
        self,
        universe: List[Symbol],
        lookback_period: int = 20,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.5,
        max_positions: int = 5,
        name: str = "MeanReversionStrategy"
    ):
        super().__init__(name)

        self.universe = universe
        self.lookback_period = lookback_period
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.max_positions = max_positions

        # Price history for each symbol
        self.price_history = {symbol: deque(maxlen=lookback_period) for symbol in universe}

        # Trading state
        self.current_date: Optional[datetime] = None
        self.last_timestamp: Optional[datetime] = None
        self.current_holdings = set()
        self.order_counter = 0

        logger.info(
            f"MeanReversionStrategy initialized: "
            f"universe={len(universe)}, "
            f"lookback={lookback_period}, "
            f"entry_threshold={entry_threshold}, "
            f"exit_threshold={exit_threshold}, "
            f"max_positions={max_positions}"
        )

    def on_initialize(self) -> None:
        """Strategy-specific initialization."""
        logger.info(f"Strategy '{self.name}' initializing...")

    def on_market_event(self, event: MarketEvent) -> None:
        """Handle market data updates."""
        symbol = event.symbol
        self.last_timestamp = event.timestamp

        # Update price history
        if symbol in self.price_history:
            self.price_history[symbol].append(event.close)

        # Track trading days (only process once per calendar date per symbol)
        event_date = event.timestamp.date()
        if self.current_date != event_date:
            self.current_date = event_date

        # Check signals for this symbol
        z_score = self._calculate_z_score(symbol)
        if z_score is None:
            return

        if symbol in self.current_holdings:
            # Exit: sell when z-score reverts above exit_threshold
            if z_score > self.exit_threshold:
                self._sell_position(symbol)
        else:
            # Entry: buy when z-score drops below -entry_threshold (oversold)
            if z_score < -self.entry_threshold:
                if len(self.current_holdings) < self.max_positions:
                    self._buy_position(symbol)

    def on_fill_event(self, event: FillEvent) -> None:
        """Handle order fill notifications."""
        logger.info(f"Fill received: {event.symbol} {event.quantity} @ {event.fill_price}")

    def get_universe(self) -> List[Symbol]:
        return self.universe

    def _next_order_id(self, prefix: str, symbol: str) -> str:
        """Generate a unique order ID."""
        self.order_counter += 1
        return f"{prefix}_{symbol}_{self.order_counter}"

    def _calculate_z_score(self, symbol: Symbol) -> Optional[float]:
        """Calculate z-score: (price - SMA) / rolling_std over lookback_period."""
        prices = self.price_history[symbol]
        if len(prices) < self.lookback_period:
            return None

        prices_list = list(prices)
        mean = sum(prices_list) / len(prices_list)
        variance = sum((p - mean) ** 2 for p in prices_list) / len(prices_list)
        std = math.sqrt(variance)

        if std == 0:
            return 0.0

        current_price = prices_list[-1]
        return (current_price - mean) / std

    def _buy_position(self, symbol: Symbol) -> None:
        """Submit a buy order for a symbol."""
        latest_price = self.price_history[symbol][-1] if self.price_history[symbol] else None
        if latest_price is None or latest_price <= 0:
            return

        # Equal weight position sizing
        portfolio_value = self.portfolio.total_value if self.portfolio else 1_000_000
        position_size = portfolio_value / self.max_positions

        quantity = int(position_size / latest_price)
        if quantity > 0:
            order = OrderEvent(
                timestamp=self.last_timestamp,
                event_type=EventType.ORDER,
                order_id=self._next_order_id("buy", symbol),
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=OrderSide.BUY,
                quantity=quantity,
                strategy_id=self.name
            )
            self.submit_order(order)
            self.current_holdings.add(symbol)
            logger.info(
                f"BUY signal: {symbol} qty={quantity} "
                f"z-score={self._calculate_z_score(symbol):.2f}"
            )

    def _sell_position(self, symbol: Symbol) -> None:
        """Submit a sell order to close a position."""
        current_position = self.get_position(symbol)
        if current_position and current_position > 0:
            order = OrderEvent(
                timestamp=self.last_timestamp,
                event_type=EventType.ORDER,
                order_id=self._next_order_id("sell", symbol),
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=OrderSide.SELL,
                quantity=current_position,
                strategy_id=self.name
            )
            self.submit_order(order)
            self.current_holdings.discard(symbol)
            logger.info(
                f"SELL signal: {symbol} qty={current_position} "
                f"z-score={self._calculate_z_score(symbol):.2f}"
            )
