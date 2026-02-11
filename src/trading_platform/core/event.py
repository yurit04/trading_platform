"""
Event classes for the event-driven architecture.
"""
from abc import ABC
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

from .enums import EventType, OrderType, OrderSide, OrderStatus, SignalType, AssetClass
from .types import Symbol, Price, Quantity, Volume, OrderId, FillId


@dataclass
class Event(ABC):
    """Base class for all events."""
    timestamp: datetime
    event_type: EventType
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'event_type': self.event_type.name
        }


@dataclass
class MarketEvent(Event):
    """Market data event (bar or tick)."""
    symbol: Symbol
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Volume
    asset_class: AssetClass = AssetClass.EQUITY
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.event_type = EventType.MARKET
    
    @property
    def price(self) -> Price:
        """Get the most recent price (close)."""
        return self.close
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'symbol': self.symbol,
            'open': float(self.open),
            'high': float(self.high),
            'low': float(self.low),
            'close': float(self.close),
            'volume': float(self.volume),
            'asset_class': self.asset_class.name,
            'metadata': self.metadata
        })
        return data


@dataclass
class SignalEvent(Event):
    """Strategy signal event."""
    symbol: Symbol
    signal_type: SignalType
    strength: float = 1.0  # Signal strength/confidence (0-1)
    target_quantity: Optional[Quantity] = None
    target_price: Optional[Price] = None
    strategy_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.event_type = EventType.SIGNAL
        if not 0 <= self.strength <= 1:
            raise ValueError(f"Signal strength must be between 0 and 1, got {self.strength}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'symbol': self.symbol,
            'signal_type': self.signal_type.name,
            'strength': self.strength,
            'target_quantity': float(self.target_quantity) if self.target_quantity else None,
            'target_price': float(self.target_price) if self.target_price else None,
            'strategy_id': self.strategy_id,
            'metadata': self.metadata
        })
        return data


@dataclass
class OrderEvent(Event):
    """Order request event."""
    order_id: OrderId
    symbol: Symbol
    order_type: OrderType
    side: OrderSide
    quantity: Quantity
    limit_price: Optional[Price] = None
    stop_price: Optional[Price] = None
    time_in_force: str = 'DAY'
    strategy_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.event_type = EventType.ORDER
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'order_id': str(self.order_id),
            'symbol': self.symbol,
            'order_type': self.order_type.name,
            'side': self.side.name,
            'quantity': float(self.quantity),
            'limit_price': float(self.limit_price) if self.limit_price else None,
            'stop_price': float(self.stop_price) if self.stop_price else None,
            'time_in_force': self.time_in_force,
            'strategy_id': self.strategy_id,
            'metadata': self.metadata
        })
        return data


@dataclass
class FillEvent(Event):
    """Order fill event."""
    fill_id: FillId
    order_id: OrderId
    symbol: Symbol
    side: OrderSide
    quantity: Quantity
    fill_price: Price
    commission: float = 0.0
    exchange: Optional[str] = None
    strategy_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.event_type = EventType.FILL
    
    @property
    def cost(self) -> float:
        """Total cost including commission."""
        return float(self.quantity * self.fill_price + self.commission)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'fill_id': str(self.fill_id),
            'order_id': str(self.order_id),
            'symbol': self.symbol,
            'side': self.side.name,
            'quantity': float(self.quantity),
            'fill_price': float(self.fill_price),
            'commission': self.commission,
            'exchange': self.exchange,
            'strategy_id': self.strategy_id,
            'cost': self.cost,
            'metadata': self.metadata
        })
        return data


@dataclass
class RiskEvent(Event):
    """Risk-related event (alerts, breaches)."""
    risk_type: str
    severity: str  # INFO, WARNING, CRITICAL
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.event_type = EventType.RISK
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'risk_type': self.risk_type,
            'severity': self.severity,
            'message': self.message,
            'details': self.details
        })
        return data


@dataclass
class TimerEvent(Event):
    """Timer event for scheduled activities."""
    timer_name: str
    scheduled_time: datetime
    callback_data: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        self.event_type = EventType.TIMER
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'timer_name': self.timer_name,
            'scheduled_time': self.scheduled_time.isoformat(),
            'callback_data': self.callback_data
        })
        return data


@dataclass
class PositionEvent(Event):
    """Position update event."""
    symbol: Symbol
    quantity: Quantity
    average_price: Price
    current_price: Price
    unrealized_pnl: float
    realized_pnl: float
    
    def __post_init__(self):
        self.event_type = EventType.POSITION
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'symbol': self.symbol,
            'quantity': float(self.quantity),
            'average_price': float(self.average_price),
            'current_price': float(self.current_price),
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl
        })
        return data


@dataclass
class PortfolioEvent(Event):
    """Portfolio-level event."""
    total_value: float
    cash: float
    positions_value: float
    unrealized_pnl: float
    realized_pnl: float
    
    def __post_init__(self):
        self.event_type = EventType.PORTFOLIO
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            'total_value': self.total_value,
            'cash': self.cash,
            'positions_value': self.positions_value,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl
        })
        return data
