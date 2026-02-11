"""
Example momentum trading strategy.
"""
from typing import List
from collections import deque
import logging

from trading_platform.strategy.base import Strategy
from trading_platform.core.event import MarketEvent, FillEvent, OrderEvent
from trading_platform.core.enums import OrderType, OrderSide, SignalType
from trading_platform.core.types import Symbol


logger = logging.getLogger(__name__)


class MomentumStrategy(Strategy):
    """
    Simple momentum strategy that buys top performers and sells bottom performers.
    
    Strategy Logic:
    1. Calculate returns over lookback period
    2. Rank securities by returns
    3. Long the top N securities
    4. Rebalance periodically
    """
    
    def __init__(
        self,
        universe: List[Symbol],
        lookback_period: int = 20,
        top_n: int = 10,
        rebalance_days: int = 5,
        name: str = "MomentumStrategy"
    ):
        """
        Initialize momentum strategy.
        
        Args:
            universe: List of symbols to trade
            lookback_period: Lookback period for momentum calculation
            top_n: Number of top performers to hold
            rebalance_days: Days between rebalances
            name: Strategy name
        """
        super().__init__(name)
        
        self.universe = universe
        self.lookback_period = lookback_period
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        
        # Price history for each symbol
        self.price_history = {symbol: deque(maxlen=lookback_period) for symbol in universe}
        
        # Trading state
        self.days_since_rebalance = 0
        self.current_holdings = set()
        
        logger.info(
            f"MomentumStrategy initialized: "
            f"universe={len(universe)}, "
            f"lookback={lookback_period}, "
            f"top_n={top_n}"
        )
    
    def on_initialize(self) -> None:
        """Strategy-specific initialization."""
        logger.info(f"Strategy '{self.name}' initializing...")
    
    def on_market_event(self, event: MarketEvent) -> None:
        """
        Handle market data updates.
        
        Args:
            event: Market data event
        """
        symbol = event.symbol
        
        # Update price history
        if symbol in self.price_history:
            self.price_history[symbol].append(event.close)
        
        # Check if it's time to rebalance
        self.days_since_rebalance += 1
        if self.days_since_rebalance >= self.rebalance_days:
            self._rebalance()
            self.days_since_rebalance = 0
    
    def on_fill_event(self, event: FillEvent) -> None:
        """
        Handle order fill notifications.
        
        Args:
            event: Fill event
        """
        logger.info(f"Fill received: {event.symbol} {event.quantity} @ {event.fill_price}")
    
    def get_universe(self) -> List[Symbol]:
        """
        Get trading universe.
        
        Returns:
            List of symbols
        """
        return self.universe
    
    def _calculate_momentum(self, symbol: Symbol) -> float:
        """
        Calculate momentum for a symbol.
        
        Args:
            symbol: Symbol to calculate momentum for
            
        Returns:
            Momentum value (return over period)
        """
        prices = self.price_history[symbol]
        if len(prices) < self.lookback_period:
            return 0.0
        
        return (prices[-1] - prices[0]) / prices[0]
    
    def _rebalance(self) -> None:
        """Rebalance the portfolio based on momentum signals."""
        logger.info("Rebalancing portfolio...")
        
        # Calculate momentum for all symbols
        momentum_scores = {}
        for symbol in self.universe:
            if len(self.price_history[symbol]) >= self.lookback_period:
                momentum_scores[symbol] = self._calculate_momentum(symbol)
        
        # Rank and select top performers
        sorted_symbols = sorted(
            momentum_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        top_symbols = set([symbol for symbol, _ in sorted_symbols[:self.top_n]])
        
        # Determine position changes
        symbols_to_buy = top_symbols - self.current_holdings
        symbols_to_sell = self.current_holdings - top_symbols
        
        # Generate orders
        portfolio_value = self.portfolio.total_value if self.portfolio else 1_000_000
        position_size = portfolio_value / self.top_n
        
        # Sell positions no longer in top N
        for symbol in symbols_to_sell:
            current_position = self.get_position(symbol)
            if current_position and current_position > 0:
                order = OrderEvent(
                    timestamp=None,  # Will be set by event bus
                    order_id=f"sell_{symbol}",
                    symbol=symbol,
                    order_type=OrderType.MARKET,
                    side=OrderSide.SELL,
                    quantity=current_position,
                    strategy_id=self.name
                )
                self.submit_order(order)
        
        # Buy new top performers
        for symbol in symbols_to_buy:
            latest_price = self.price_history[symbol][-1] if self.price_history[symbol] else 100
            quantity = int(position_size / latest_price)
            
            if quantity > 0:
                order = OrderEvent(
                    timestamp=None,  # Will be set by event bus
                    order_id=f"buy_{symbol}",
                    symbol=symbol,
                    order_type=OrderType.MARKET,
                    side=OrderSide.BUY,
                    quantity=quantity,
                    strategy_id=self.name
                )
                self.submit_order(order)
        
        self.current_holdings = top_symbols
        logger.info(f"Rebalance complete. Holdings: {self.current_holdings}")
