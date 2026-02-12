"""
Interactive Brokers broker adapter using ib_insync.
"""
from typing import Dict, Any, Optional, List, Callable
from uuid import uuid4
import logging

from ...core.event import FillEvent
from ...core.enums import OrderSide, OrderType, EventType
from ...data.models import Bar
from ..order import Order

try:
    from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder, StopLimitOrder, Trade
    HAS_IB_INSYNC = True
except ImportError:
    HAS_IB_INSYNC = False


logger = logging.getLogger(__name__)


# Mapping from platform OrderType to IB order constructors
_ORDER_TYPE_MAP = {
    OrderType.MARKET: 'MKT',
    OrderType.LIMIT: 'LMT',
    OrderType.STOP: 'STP',
    OrderType.STOP_LIMIT: 'STP LMT',
}

# Mapping from platform OrderSide to IB action strings
_SIDE_MAP = {
    OrderSide.BUY: 'BUY',
    OrderSide.SELL: 'SELL',
    OrderSide.SELL_SHORT: 'SELL',
    OrderSide.BUY_TO_COVER: 'BUY',
}


class IBBroker:
    """
    Interactive Brokers broker adapter.

    Connects to TWS or IB Gateway via ib_insync and executes orders,
    queries positions, and subscribes to real-time market data.
    """

    def __init__(self, config: Dict[str, Any]):
        if not HAS_IB_INSYNC:
            raise ImportError(
                "ib_insync is required for IBBroker. "
                "Install it with: pip install ib_insync"
            )

        self.host = config.get('ib_host', '127.0.0.1')
        self.port = config.get('ib_port', 7497)  # 7497 = paper, 7496 = live
        self.client_id = config.get('ib_client_id', 1)
        self.account = config.get('ib_account', '')
        self.timeout = config.get('ib_timeout', 30)

        # Commission config (for fill events; IB reports actual commissions)
        self.commission_per_share = config.get('commission_rate', 0.005)

        self.ib = IB()
        self._connected = False

        logger.info(
            f"IBBroker initialized: host={self.host}, port={self.port}, "
            f"client_id={self.client_id}"
        )

    def connect(self) -> None:
        """Establish connection to IB TWS/Gateway."""
        if self._connected:
            logger.warning("IBBroker already connected")
            return

        try:
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=self.timeout,
                readonly=False
            )
            self._connected = True

            # Set account if specified
            if self.account:
                logger.info(f"Using IB account: {self.account}")
            else:
                accounts = self.ib.managedAccounts()
                if accounts:
                    self.account = accounts[0]
                    logger.info(f"Auto-selected IB account: {self.account}")

            logger.info("IBBroker connected to TWS/Gateway")

        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            raise ConnectionError(f"Failed to connect to IB TWS/Gateway: {e}")

    def disconnect(self) -> None:
        """Disconnect from IB TWS/Gateway."""
        if self._connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("IBBroker disconnected")

    def _ensure_connected(self) -> None:
        """Raise if not connected."""
        if not self._connected or not self.ib.isConnected():
            raise ConnectionError("IBBroker is not connected to TWS/Gateway")

    def execute_order(self, order: Order, current_bar: Bar) -> FillEvent:
        """
        Execute an order through Interactive Brokers.

        Converts the platform Order to an IB contract and order, places it,
        and waits for the fill.

        Args:
            order: Order to execute
            current_bar: Current market bar (used for timestamp)

        Returns:
            FillEvent with execution details
        """
        self._ensure_connected()

        # Create IB contract (default to US stock)
        contract = Stock(order.symbol, 'SMART', 'USD')

        # Create IB order
        ib_order = self._create_ib_order(order)

        logger.info(
            f"Placing IB order: {ib_order.action} {ib_order.totalQuantity} "
            f"{order.symbol} {ib_order.orderType}"
        )

        # Place order and wait for fill
        trade: Trade = self.ib.placeOrder(contract, ib_order)

        # Wait for the order to fill (blocking)
        while not trade.isDone():
            self.ib.waitOnUpdate(timeout=self.timeout)

        if trade.orderStatus.status == 'Filled':
            fill_price = trade.orderStatus.avgFillPrice
            filled_qty = trade.orderStatus.filled
            commission = self._get_commission(trade)

            fill = FillEvent(
                timestamp=current_bar.timestamp,
                event_type=EventType.FILL,
                fill_id=str(uuid4()),
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=filled_qty,
                fill_price=fill_price,
                commission=commission,
                strategy_id=order.strategy_id
            )

            logger.info(
                f"IB order filled: {order.side.name} {filled_qty} {order.symbol} "
                f"@ {fill_price:.2f} (commission: {commission:.2f})"
            )

            return fill
        else:
            status = trade.orderStatus.status
            raise RuntimeError(
                f"IB order not filled. Status: {status}, "
                f"Symbol: {order.symbol}, Side: {order.side.name}"
            )

    def _create_ib_order(self, order: Order):
        """
        Convert a platform Order to an ib_insync order object.

        Args:
            order: Platform order

        Returns:
            ib_insync order object
        """
        action = _SIDE_MAP.get(order.side, 'BUY')
        quantity = abs(order.quantity)

        if order.order_type == OrderType.MARKET:
            return MarketOrder(action, quantity)
        elif order.order_type == OrderType.LIMIT:
            return LimitOrder(action, quantity, order.limit_price)
        elif order.order_type == OrderType.STOP:
            return StopOrder(action, quantity, order.stop_price)
        elif order.order_type == OrderType.STOP_LIMIT:
            return StopLimitOrder(action, quantity, order.stop_price, order.limit_price)
        else:
            logger.warning(
                f"Unsupported order type {order.order_type}, defaulting to MARKET"
            )
            return MarketOrder(action, quantity)

    def _get_commission(self, trade: 'Trade') -> float:
        """
        Extract commission from an IB trade.

        Falls back to estimated commission if actual is not available.
        """
        total_commission = 0.0
        for fill in trade.fills:
            total_commission += fill.commissionReport.commission
        if total_commission == 0.0:
            # Fallback estimate
            total_commission = abs(trade.orderStatus.filled) * self.commission_per_share
        return total_commission

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Query current positions from IB.

        Returns:
            List of position dictionaries with symbol, quantity, avg_cost,
            market_value, and unrealized_pnl.
        """
        self._ensure_connected()

        positions = []
        for pos in self.ib.positions(account=self.account):
            positions.append({
                'symbol': pos.contract.symbol,
                'quantity': pos.position,
                'avg_cost': pos.avgCost,
                'contract': {
                    'sec_type': pos.contract.secType,
                    'exchange': pos.contract.exchange,
                    'currency': pos.contract.currency,
                }
            })

        logger.info(f"Retrieved {len(positions)} positions from IB")
        return positions

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Query account summary from IB.

        Returns:
            Dictionary with account metrics: net_liquidation, total_cash,
            buying_power, gross_position_value, etc.
        """
        self._ensure_connected()

        summary = {}
        tags = [
            'NetLiquidation', 'TotalCashValue', 'BuyingPower',
            'GrossPositionValue', 'MaintMarginReq', 'AvailableFunds',
            'ExcessLiquidity', 'UnrealizedPnL', 'RealizedPnL'
        ]

        account_values = self.ib.accountSummary(account=self.account)
        for av in account_values:
            if av.tag in tags:
                try:
                    summary[av.tag] = float(av.value)
                except (ValueError, TypeError):
                    summary[av.tag] = av.value

        logger.info(f"Retrieved account summary: {len(summary)} fields")
        return summary

    def subscribe_market_data(
        self,
        symbols: List[str],
        callback: Callable
    ) -> None:
        """
        Subscribe to real-time 5-second bars from IB.

        Args:
            symbols: List of ticker symbols to subscribe to
            callback: Function called with (symbol, bar_data) on each update
        """
        self._ensure_connected()

        for symbol in symbols:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)

            bars = self.ib.reqRealTimeBars(
                contract,
                barSize=5,
                whatToShow='MIDPOINT',
                useRTH=True
            )

            def _on_bar_update(bars, hasNewBar, sym=symbol, cb=callback):
                if hasNewBar and len(bars) > 0:
                    bar = bars[-1]
                    bar_data = Bar(
                        symbol=sym,
                        timestamp=bar.time,
                        open=bar.open_,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=float(bar.volume)
                    )
                    cb(sym, bar_data)

            bars.updateEvent += _on_bar_update
            logger.info(f"Subscribed to real-time bars for {symbol}")

    def cancel_order(self, trade: 'Trade') -> None:
        """Cancel an active IB order."""
        self._ensure_connected()
        self.ib.cancelOrder(trade.order)
        logger.info(f"Cancelled IB order: {trade.order.orderId}")

    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        self._ensure_connected()
        self.ib.reqGlobalCancel()
        logger.info("Cancelled all open IB orders")

    def __del__(self):
        """Ensure disconnection on garbage collection."""
        try:
            self.disconnect()
        except Exception:
            pass
