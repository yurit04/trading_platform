"""
Common type definitions used throughout the platform.
"""
from typing import Dict, List, Optional, Union, Any, Callable, TypeVar
from datetime import datetime, date
from decimal import Decimal

# Basic types
Symbol = str
Timestamp = datetime
Price = Union[float, Decimal]
Quantity = Union[float, Decimal, int]
Volume = Union[float, int]
BarDict = Dict[str, Any]

# Collection types
Symbols = List[Symbol]
PriceDict = Dict[Symbol, Price]
QuantityDict = Dict[Symbol, Quantity]

# Callback types
T = TypeVar('T')
EventCallback = Callable[[Any], None]
DataCallback = Callable[[Symbol, BarDict], None]

# Time types
DateLike = Union[datetime, date, str]
TimeDelta = Union[int, float]

# Financial types
Returns = float
Volatility = float
Beta = float
Sharpe = float

# Order types
OrderId = Union[str, int]
FillId = Union[str, int]
PositionId = Union[str, int]

# Configuration types
ConfigDict = Dict[str, Any]
ParametersDict = Dict[str, Any]
