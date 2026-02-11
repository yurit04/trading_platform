"""
Custom exceptions for the trading platform.
"""


class PlatformException(Exception):
    """Base exception for all platform errors."""
    pass


# Data exceptions
class DataException(PlatformException):
    """Base exception for data-related errors."""
    pass


class DataNotAvailableException(DataException):
    """Raised when requested data is not available."""
    pass


class DataValidationException(DataException):
    """Raised when data fails validation checks."""
    pass


class DataProviderException(DataException):
    """Raised when data provider encounters an error."""
    pass


# Strategy exceptions
class StrategyException(PlatformException):
    """Base exception for strategy-related errors."""
    pass


class StrategyConfigurationException(StrategyException):
    """Raised when strategy configuration is invalid."""
    pass


class StrategyExecutionException(StrategyException):
    """Raised when strategy execution fails."""
    pass


# Execution exceptions
class ExecutionException(PlatformException):
    """Base exception for execution-related errors."""
    pass


class OrderValidationException(ExecutionException):
    """Raised when order fails validation."""
    pass


class OrderRejectionException(ExecutionException):
    """Raised when broker rejects an order."""
    pass


class InsufficientFundsException(ExecutionException):
    """Raised when insufficient funds for order."""
    pass


class BrokerConnectionException(ExecutionException):
    """Raised when broker connection fails."""
    pass


# Risk exceptions
class RiskException(PlatformException):
    """Base exception for risk-related errors."""
    pass


class RiskLimitExceededException(RiskException):
    """Raised when risk limit is exceeded."""
    def __init__(self, limit_name: str, limit_value: float, actual_value: float, message: str = None):
        self.limit_name = limit_name
        self.limit_value = limit_value
        self.actual_value = actual_value
        if message is None:
            message = (
                f"Risk limit '{limit_name}' exceeded: "
                f"limit={limit_value}, actual={actual_value}"
            )
        super().__init__(message)


class PreTradeCheckFailedException(RiskException):
    """Raised when pre-trade checks fail."""
    pass


# Portfolio exceptions
class PortfolioException(PlatformException):
    """Base exception for portfolio-related errors."""
    pass


class InsufficientPositionException(PortfolioException):
    """Raised when trying to sell more than owned."""
    pass


class PositionNotFoundException(PortfolioException):
    """Raised when position is not found."""
    pass


# Configuration exceptions
class ConfigurationException(PlatformException):
    """Base exception for configuration errors."""
    pass


class InvalidConfigurationException(ConfigurationException):
    """Raised when configuration is invalid."""
    pass


class MissingConfigurationException(ConfigurationException):
    """Raised when required configuration is missing."""
    pass


# Engine exceptions
class EngineException(PlatformException):
    """Base exception for engine-related errors."""
    pass


class EngineNotInitializedException(EngineException):
    """Raised when engine is not properly initialized."""
    pass


class EngineAlreadyRunningException(EngineException):
    """Raised when trying to start an already running engine."""
    pass


# Event exceptions
class EventException(PlatformException):
    """Base exception for event-related errors."""
    pass


class InvalidEventException(EventException):
    """Raised when event is invalid."""
    pass


class EventHandlerException(EventException):
    """Raised when event handler encounters an error."""
    pass
