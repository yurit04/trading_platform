"""
Order class for managing order state and properties.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4

from ..core.enums import OrderType, OrderSide, OrderStatus, TimeInForce
from ..core.types import Symbol, Price, Quantity, OrderId


@dataclass
class Order:
    """
    Represents a trading order.
    """
    symbol: Symbol
    order_type: OrderType
    side: OrderSide
    quantity: Quantity
    limit_price: Optional[Price] = None
    stop_price: Optional[Price] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    
    # Generated fields
    order_id: OrderId = field(default_factory=lambda: str(uuid4()))
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Execution tracking
    filled_quantity: Quantity = 0
    average_fill_price: Optional[Price] = None
    commission: float = 0.0
    
    # Metadata
    strategy_id: Optional[str] = None
    notes: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate order parameters."""
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive: {self.quantity}")
        
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("Limit price required for limit orders")
        
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("Stop price required for stop orders")
        
        if self.order_type == OrderType.STOP_LIMIT:
            if self.limit_price is None or self.stop_price is None:
                raise ValueError("Both limit and stop price required for stop-limit orders")
    
    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == OrderStatus.FILLED
    
    @property
    def is_active(self) -> bool:
        """Check if order is active (can still be filled)."""
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED
        )
    
    @property
    def remaining_quantity(self) -> Quantity:
        """Get remaining unfilled quantity."""
        return self.quantity - self.filled_quantity
    
    @property
    def fill_percentage(self) -> float:
        """Get percentage of order filled."""
        if self.quantity == 0:
            return 0.0
        return (self.filled_quantity / self.quantity) * 100
    
    def update_fill(self, quantity: Quantity, price: Price, commission: float = 0.0) -> None:
        """
        Update order with fill information.
        
        Args:
            quantity: Filled quantity
            price: Fill price
            commission: Commission charged
        """
        if quantity <= 0:
            raise ValueError(f"Fill quantity must be positive: {quantity}")
        
        if self.filled_quantity + quantity > self.quantity:
            raise ValueError("Fill quantity exceeds order quantity")
        
        # Update average fill price
        if self.average_fill_price is None:
            self.average_fill_price = price
        else:
            total_value = (self.average_fill_price * self.filled_quantity) + (price * quantity)
            self.filled_quantity += quantity
            self.average_fill_price = total_value / self.filled_quantity
        
        self.filled_quantity += quantity
        self.commission += commission
        self.updated_at = datetime.now()
        
        # Update status
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIALLY_FILLED
    
    def cancel(self) -> None:
        """Cancel the order."""
        if not self.is_active:
            raise ValueError(f"Cannot cancel order with status: {self.status}")
        
        self.status = OrderStatus.CANCELLED
        self.updated_at = datetime.now()
    
    def reject(self, reason: Optional[str] = None) -> None:
        """
        Reject the order.
        
        Args:
            reason: Rejection reason
        """
        self.status = OrderStatus.REJECTED
        self.updated_at = datetime.now()
        if reason:
            self.notes = reason
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert order to dictionary."""
        return {
            'order_id': str(self.order_id),
            'symbol': self.symbol,
            'order_type': self.order_type.name,
            'side': self.side.name,
            'quantity': float(self.quantity),
            'limit_price': float(self.limit_price) if self.limit_price else None,
            'stop_price': float(self.stop_price) if self.stop_price else None,
            'time_in_force': self.time_in_force.name,
            'status': self.status.name,
            'filled_quantity': float(self.filled_quantity),
            'average_fill_price': float(self.average_fill_price) if self.average_fill_price else None,
            'commission': self.commission,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'strategy_id': self.strategy_id,
            'notes': self.notes,
            'metadata': self.metadata
        }
    
    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id[:8]}..., "
            f"symbol={self.symbol}, "
            f"type={self.order_type.name}, "
            f"side={self.side.name}, "
            f"quantity={self.quantity}, "
            f"status={self.status.name})"
        )
