"""
Core enumerations used throughout the platform.
"""
from enum import Enum, auto


class OrderType(Enum):
    """Order types supported by the platform."""
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()
    MOC = auto()  # Market on Close
    MOO = auto()  # Market on Open
    LOC = auto()  # Limit on Close
    LOO = auto()  # Limit on Open
    TWAP = auto()  # Time-Weighted Average Price
    VWAP = auto()  # Volume-Weighted Average Price
    ICEBERG = auto()
    HIDDEN = auto()


class OrderSide(Enum):
    """Order side (direction)."""
    BUY = auto()
    SELL = auto()
    SELL_SHORT = auto()
    BUY_TO_COVER = auto()


class OrderStatus(Enum):
    """Order lifecycle status."""
    PENDING = auto()
    SUBMITTED = auto()
    ACCEPTED = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


class TimeInForce(Enum):
    """Time in force specifications."""
    DAY = auto()
    GTC = auto()  # Good Till Cancelled
    IOC = auto()  # Immediate or Cancel
    FOK = auto()  # Fill or Kill
    GTD = auto()  # Good Till Date
    OPG = auto()  # At the Opening
    CLS = auto()  # At the Close


class AssetClass(Enum):
    """Asset class types."""
    EQUITY = auto()
    ETF = auto()
    FUTURE = auto()
    OPTION = auto()
    CRYPTO = auto()
    FX = auto()
    COMMODITY = auto()
    BOND = auto()


class SignalType(Enum):
    """Strategy signal types."""
    LONG = auto()
    SHORT = auto()
    EXIT_LONG = auto()
    EXIT_SHORT = auto()
    HOLD = auto()


class EventType(Enum):
    """Event types in the event bus."""
    MARKET = auto()
    SIGNAL = auto()
    ORDER = auto()
    FILL = auto()
    RISK = auto()
    TIMER = auto()
    POSITION = auto()
    PORTFOLIO = auto()


class EngineMode(Enum):
    """Trading engine mode."""
    BACKTEST = auto()
    PAPER = auto()
    LIVE = auto()


class RiskLimitType(Enum):
    """Types of risk limits."""
    POSITION_SIZE = auto()
    LEVERAGE = auto()
    SECTOR_EXPOSURE = auto()
    CONCENTRATION = auto()
    VOLATILITY = auto()
    VAR = auto()
    DRAWDOWN = auto()


class BarFrequency(Enum):
    """Bar data frequency."""
    TICK = auto()
    SECOND_1 = auto()
    SECOND_5 = auto()
    SECOND_15 = auto()
    SECOND_30 = auto()
    MINUTE_1 = auto()
    MINUTE_5 = auto()
    MINUTE_15 = auto()
    MINUTE_30 = auto()
    HOUR_1 = auto()
    HOUR_4 = auto()
    DAY_1 = auto()
    WEEK_1 = auto()
    MONTH_1 = auto()


class CorporateActionType(Enum):
    """Corporate action types."""
    SPLIT = auto()
    REVERSE_SPLIT = auto()
    DIVIDEND = auto()
    SPECIAL_DIVIDEND = auto()
    SPIN_OFF = auto()
    MERGER = auto()
    DELISTING = auto()


class ExecutionVenue(Enum):
    """Execution venues/exchanges."""
    NYSE = auto()
    NASDAQ = auto()
    ARCA = auto()
    BATS = auto()
    IEX = auto()
    CME = auto()
    CBOE = auto()
    BINANCE = auto()
    COINBASE = auto()
    KRAKEN = auto()
    FTX = auto()


class DataSource(Enum):
    """Data source types."""
    CSV = auto()
    SQL = auto()
    API = auto()
    LIVE_FEED = auto()
    PARQUET = auto()


class SlippageModel(Enum):
    """Slippage model types."""
    FIXED = auto()
    PERCENTAGE = auto()
    VOLUME_BASED = auto()
    SQRT_VOLUME = auto()
    CUSTOM = auto()


class CommissionModel(Enum):
    """Commission model types."""
    FIXED_PER_TRADE = auto()
    FIXED_PER_SHARE = auto()
    PERCENTAGE = auto()
    TIERED = auto()
    CUSTOM = auto()
