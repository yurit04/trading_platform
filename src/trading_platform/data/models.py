"""
Data models for market data.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

from ..core.types import Symbol, Price, Volume
from ..core.enums import AssetClass, BarFrequency


@dataclass
class Bar:
    """
    OHLCV bar data.
    """
    timestamp: datetime
    symbol: Symbol
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Volume
    frequency: BarFrequency = BarFrequency.DAY_1
    asset_class: AssetClass = AssetClass.EQUITY
    
    # Optional fields
    vwap: Optional[Price] = None
    trades: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate bar data."""
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(f"High ({self.high}) must be >= open and close")
        if self.low > self.open or self.low > self.close:
            raise ValueError(f"Low ({self.low}) must be <= open and close")
        if self.volume < 0:
            raise ValueError(f"Volume cannot be negative: {self.volume}")
    
    @property
    def typical_price(self) -> Price:
        """Calculate typical price (HLC/3)."""
        return (self.high + self.low + self.close) / 3
    
    @property
    def range(self) -> Price:
        """Calculate bar range (high - low)."""
        return self.high - self.low
    
    @property
    def body(self) -> Price:
        """Calculate bar body (close - open)."""
        return self.close - self.open
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'open': float(self.open),
            'high': float(self.high),
            'low': float(self.low),
            'close': float(self.close),
            'volume': float(self.volume),
            'frequency': self.frequency.name,
            'asset_class': self.asset_class.name,
            'vwap': float(self.vwap) if self.vwap else None,
            'trades': self.trades,
            'metadata': self.metadata
        }


@dataclass
class Tick:
    """
    Tick-level market data.
    """
    timestamp: datetime
    symbol: Symbol
    price: Price
    size: Volume
    bid: Optional[Price] = None
    ask: Optional[Price] = None
    bid_size: Optional[Volume] = None
    ask_size: Optional[Volume] = None
    
    @property
    def spread(self) -> Optional[Price]:
        """Calculate bid-ask spread."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None
    
    @property
    def mid_price(self) -> Optional[Price]:
        """Calculate mid price."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'price': float(self.price),
            'size': float(self.size),
            'bid': float(self.bid) if self.bid else None,
            'ask': float(self.ask) if self.ask else None,
            'bid_size': float(self.bid_size) if self.bid_size else None,
            'ask_size': float(self.ask_size) if self.ask_size else None,
        }


@dataclass
class Quote:
    """
    Quote data (bid/ask).
    """
    timestamp: datetime
    symbol: Symbol
    bid: Price
    ask: Price
    bid_size: Volume
    ask_size: Volume
    
    @property
    def spread(self) -> Price:
        """Calculate bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def mid_price(self) -> Price:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'bid': float(self.bid),
            'ask': float(self.ask),
            'bid_size': float(self.bid_size),
            'ask_size': float(self.ask_size),
        }
