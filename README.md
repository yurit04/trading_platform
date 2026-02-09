# Algorithmic Trading Platform

A comprehensive, production-ready algorithmic trading platform for systematic trading across equities, ETFs, futures, and cryptocurrency markets. Built in Python with a focus on robust backtesting, seamless live deployment, and institutional-grade risk management.

## Table of Contents

- [Overview](#overview)
- [Core Features](#core-features)
- [System Architecture](#system-architecture)
- [Directory Structure](#directory-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
- [Component Details](#component-details)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)

## Overview

This platform enables quantitative traders to develop, test, and deploy systematic trading strategies with confidence. The architecture ensures that strategies tested in backtesting behave identically in live trading, reducing implementation risk and accelerating strategy deployment.

### Design Principles

1. **Mode Agnostic Strategies** - Write once, run in both backtest and live modes
2. **Event-Driven Architecture** - Realistic simulation and concurrent strategy execution
3. **Asset Class Abstraction** - Unified interface across equities, futures, and crypto
4. **Data Integrity** - Point-in-time data with corporate action adjustments
5. **Risk-First Design** - Pre-trade checks and portfolio-level risk monitoring

## Core Features

### Multi-Asset Support
- **Equities & ETFs**: US markets with split/dividend adjustments
- **Futures**: Commodity, index, and financial futures with roll handling
- **Cryptocurrency**: Major exchanges with 24/7 trading support

### Backtesting Engine
- Event-driven simulation for realistic testing
- Multiple fill models (conservative, aggressive, volume-based)
- Configurable slippage and transaction costs
- Point-in-time data to prevent look-ahead bias
- Corporate action handling

### Live Trading
- Real-time market data processing
- Smart order routing across brokers
- Position and risk monitoring
- Execution quality analytics
- Seamless paper trading mode

### Risk Management
- Pre-trade position and leverage limits
- Real-time PnL tracking
- VaR and portfolio risk metrics
- Drawdown-based exposure scaling
- Automated risk alerts

### Analytics & Reporting
- Comprehensive performance metrics (Sharpe, Sortino, Calmar)
- Factor attribution analysis
- Interactive visualizations
- HTML/PDF tearsheet generation
- Execution quality analysis

## System Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Strategy Layer                          │
│  (User-defined strategies, signals, portfolio construction) │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                   Execution Engine                          │
│     (Order management, routing, fills, slippage)            │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                    Event Bus                                │
│  (Market data, orders, fills, signals, risk events)         │
└───┬─────────┬──────────┬──────────┬─────────────────────────┘
    │         │          │          │
┌───▼───┐ ┌──▼────┐ ┌───▼────┐ ┌──▼─────┐
│ Data  │ │ Risk  │ │Position│ │Analytics│
│Manager│ │Manager│ │Manager │ │ Engine  │
└───────┘ └───────┘ └────────┘ └─────────┘
```

### Data Flow

**Backtest Mode:**
```
Historical Data → Event Bus → Strategy → Orders → Simulated Execution → 
Portfolio Updates → Analytics
```

**Live Mode:**
```
Market Data Feeds → Event Bus → Strategy → Orders → Risk Checks → 
Broker API → Fill Confirmations → Portfolio Updates → Analytics
```

### Component Responsibilities

#### 1. Data Management Layer
- Fetch, store, and serve historical and live market data
- Handle multiple data vendors and asset classes
- Ensure point-in-time correctness for backtesting
- Data normalization and cleaning
- Corporate actions (splits, dividends) handling

**Technology Stack:**
- TimescaleDB/InfluxDB for time-series data
- PostgreSQL for reference data
- Parquet files for fast backtesting
- Redis for real-time caching

#### 2. Event System
- Central message broker with topic subscription
- Synchronous in backtest mode for determinism
- Asynchronous (asyncio) in live mode for concurrency
- Event replay capability for debugging

**Event Types:**
- `MarketEvent` - Price updates, order book changes
- `SignalEvent` - Strategy-generated signals
- `OrderEvent` - Order requests from strategies
- `FillEvent` - Execution confirmations
- `RiskEvent` - Risk limit breaches, margin calls
- `TimerEvent` - Scheduled events (EOD, rebalance)

#### 3. Strategy Framework
Provides a unified interface for strategy development with lifecycle management:

1. Initialize (load parameters, allocate capital)
2. Process market events
3. Generate signals
4. Calculate target positions
5. Generate orders
6. Handle fills and update state
7. End-of-day reconciliation

**Components:**
- `Strategy` - Base strategy interface
- `AlphaModel` - Generates forecasts/signals
- `PortfolioConstructor` - Converts signals to target positions
- `RiskModel` - Portfolio-level risk constraints
- `ExecutionModel` - Determines order sizing and timing

#### 4. Execution Engine
- Order management and lifecycle tracking
- Smart order routing across brokers
- Simulated execution for backtesting
- Transaction cost modeling
- Fill simulation with realistic slippage

**Supported Order Types:**
- Market, Limit, Stop, Stop-Limit
- MOC, MOO, LOC, LOO (market on close/open)
- TWAP, VWAP (algorithmic)
- Iceberg, Hidden

#### 5. Risk Management
**Pre-Trade Checks:**
- Position size limits (per symbol, sector, asset class)
- Leverage limits
- Concentration limits
- Volatility-adjusted position sizing
- Drawdown-based exposure scaling

**Post-Trade Monitoring:**
- Real-time PnL tracking
- VaR and CVaR calculation
- Greeks for options/futures
- Margin utilization
- Correlation monitoring

#### 6. Portfolio Management
- Position tracking across asset classes
- Cash management and margin calculation
- Performance attribution
- Corporate action processing

#### 7. Analytics and Reporting
**Backtesting Metrics:**
- Total return, CAGR, Sharpe ratio
- Maximum drawdown, recovery time
- Win rate, profit factor
- Turnover, transaction costs
- Factor exposures over time

**Live Trading Metrics:**
- Real-time PnL
- Slippage vs expectations
- Fill rates and execution quality
- Strategy capacity utilization

## Directory Structure

```
trading_platform/
│
├── README.md                        # This file
├── setup.py                         # Package installation
├── requirements.txt                 # Python dependencies
├── docker-compose.yml               # Docker services
├── .env.example                     # Environment variables template
│
├── config/                          # Configuration files
│   ├── system.yaml                 # System-wide settings
│   ├── brokers/                    # Broker configurations
│   │   ├── interactive_brokers.yaml
│   │   ├── binance.yaml
│   │   └── coinbase.yaml
│   ├── data_providers/             # Data source configs
│   │   ├── polygon.yaml
│   │   └── cryptocompare.yaml
│   └── strategies/                 # Strategy parameters
│       ├── mean_reversion.yaml
│       └── momentum.yaml
│
├── src/
│   └── platform/
│       │
│       ├── __init__.py
│       │
│       ├── core/                   # Core abstractions
│       │   ├── __init__.py
│       │   ├── event.py           # Event base classes
│       │   ├── event_bus.py       # Event distribution
│       │   ├── engine.py          # Main engine orchestration
│       │   ├── types.py           # Common type definitions
│       │   ├── enums.py           # Enums (OrderType, Side, etc.)
│       │   └── exceptions.py      # Custom exceptions
│       │
│       ├── data/                   # Data management
│       │   ├── __init__.py
│       │   ├── manager.py         # DataManager
│       │   ├── providers/         # Data provider implementations
│       │   │   ├── __init__.py
│       │   │   ├── base.py       # Abstract provider
│       │   │   ├── csv_provider.py
│       │   │   ├── sql_provider.py
│       │   │   ├── polygon_provider.py
│       │   │   └── crypto_provider.py
│       │   ├── models.py          # Data models (Bar, Tick)
│       │   ├── storage/           # Storage backends
│       │   │   ├── __init__.py
│       │   │   ├── timeseries_db.py
│       │   │   ├── parquet_store.py
│       │   │   └── cache.py
│       │   ├── adjustments.py     # Corporate actions
│       │   └── validation.py      # Data quality checks
│       │
│       ├── strategy/              # Strategy framework
│       │   ├── __init__.py
│       │   ├── base.py           # Strategy abstract class
│       │   ├── context.py        # StrategyContext
│       │   ├── alpha/            # Alpha generation
│       │   │   ├── __init__.py
│       │   │   └── models.py
│       │   ├── portfolio/        # Portfolio construction
│       │   │   ├── __init__.py
│       │   │   ├── constructor.py
│       │   │   └── optimizer.py
│       │   ├── execution/        # Execution algorithms
│       │   │   ├── __init__.py
│       │   │   ├── twap.py
│       │   │   └── vwap.py
│       │   └── universe/         # Universe selection
│       │       ├── __init__.py
│       │       └── filters.py
│       │
│       ├── execution/             # Order execution
│       │   ├── __init__.py
│       │   ├── engine.py         # ExecutionEngine
│       │   ├── order.py          # Order class
│       │   ├── order_manager.py  # Order lifecycle
│       │   ├── brokers/          # Broker integrations
│       │   │   ├── __init__.py
│       │   │   ├── base.py       # Abstract broker
│       │   │   ├── simulated.py  # Backtest broker
│       │   │   ├── ib_broker.py
│       │   │   └── crypto_broker.py
│       │   ├── slippage.py       # Slippage models
│       │   └── costs.py          # Transaction costs
│       │
│       ├── risk/                  # Risk management
│       │   ├── __init__.py
│       │   ├── manager.py        # RiskManager
│       │   ├── limits.py         # Risk limits
│       │   ├── checks.py         # Pre-trade checks
│       │   ├── metrics.py        # Risk calculations
│       │   └── alerts.py         # Alert system
│       │
│       ├── portfolio/             # Portfolio management
│       │   ├── __init__.py
│       │   ├── portfolio.py      # Portfolio class
│       │   ├── position.py       # Position tracking
│       │   ├── cash.py           # Cash management
│       │   ├── performance.py    # Performance tracking
│       │   └── attribution.py    # Attribution analysis
│       │
│       ├── analytics/             # Analytics and reporting
│       │   ├── __init__.py
│       │   ├── backtest.py       # Backtest analyzer
│       │   ├── metrics.py        # Performance metrics
│       │   ├── statistics.py     # Statistical functions
│       │   ├── visualization.py  # Plotting utilities
│       │   └── reports.py        # Report generation
│       │
│       ├── assets/                # Asset class handling
│       │   ├── __init__.py
│       │   ├── base.py           # Asset abstract class
│       │   ├── equity.py         # Equity/ETF
│       │   ├── future.py         # Futures
│       │   ├── crypto.py         # Cryptocurrency
│       │   └── calendar.py       # Trading calendars
│       │
│       └── utils/                 # Utilities
│           ├── __init__.py
│           ├── config.py         # Configuration loader
│           ├── logging.py        # Logging setup
│           ├── database.py       # Database utilities
│           ├── validation.py     # Input validation
│           └── math.py           # Mathematical helpers
│
├── strategies/                    # User strategy implementations
│   ├── __init__.py
│   ├── examples/
│   │   ├── __init__.py
│   │   ├── mean_reversion.py
│   │   ├── momentum.py
│   │   └── pairs_trading.py
│   └── research/                 # Strategy research notebooks
│
├── scripts/                       # Operational scripts
│   ├── backtest.py               # Run backtests
│   ├── live_trading.py           # Start live trading
│   ├── data_download.py          # Data management
│   ├── optimize_parameters.py    # Parameter optimization
│   └── generate_report.py        # Create reports
│
├── tests/                         # Test suite
│   ├── __init__.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_data.py
│   │   ├── test_strategy.py
│   │   ├── test_execution.py
│   │   ├── test_risk.py
│   │   └── test_portfolio.py
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_backtest_flow.py
│   │   └── test_live_flow.py
│   └── fixtures/
│       ├── __init__.py
│       └── sample_data.py
│
├── notebooks/                     # Jupyter notebooks
│   ├── strategy_research.ipynb
│   ├── backtest_analysis.ipynb
│   └── performance_review.ipynb
│
├── data/                          # Data storage (gitignored)
│   ├── historical/
│   ├── reference/
│   └── cache/
│
├── logs/                          # Log files (gitignored)
│
└── results/                       # Backtest results (gitignored)
    ├── backtests/
    └── reports/
```

## Installation

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Redis 6+
- Docker (optional, for containerized deployment)

### Basic Installation

```bash
# Clone the repository
git clone https://github.com/yourorg/trading_platform.git
cd trading_platform

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package in development mode
pip install -e .

# Set up configuration
cp .env.example .env
# Edit .env with your settings

# Initialize database
python scripts/init_database.py
```

### Docker Installation

```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f platform
```

## Quick Start

### Running Your First Backtest

```python
from platform.core.engine import BacktestEngine
from strategies.examples.momentum import MomentumStrategy
from datetime import datetime

# Create backtest engine
engine = BacktestEngine(
    start_date=datetime(2020, 1, 1),
    end_date=datetime(2023, 12, 31),
    initial_capital=1_000_000
)

# Add strategy
strategy = MomentumStrategy(
    lookback_period=20,
    top_n=10
)
engine.add_strategy(strategy)

# Run backtest
results = engine.run()

# Display results
print(results.summary())
results.plot_equity_curve()
results.generate_tearsheet('results/momentum_backtest.html')
```

### Transitioning to Live Trading

```python
from platform.core.engine import LiveTradingEngine
from strategies.examples.momentum import MomentumStrategy

# Create live trading engine (same strategy class!)
engine = LiveTradingEngine(
    broker='interactive_brokers',
    paper_trading=True  # Start with paper trading
)

# Add the same strategy
strategy = MomentumStrategy(
    lookback_period=20,
    top_n=10
)
engine.add_strategy(strategy)

# Start live trading
engine.start()
```

## Usage Examples

### Creating a Custom Strategy

```python
from platform.strategy.base import Strategy
from platform.core.event import MarketEvent, SignalEvent
from platform.core.enums import SignalType

class MyStrategy(Strategy):
    def __init__(self, param1, param2):
        super().__init__()
        self.param1 = param1
        self.param2 = param2
        
    def on_market_event(self, event: MarketEvent):
        """Process market data and generate signals"""
        symbol = event.symbol
        price = event.close
        
        # Your strategy logic here
        signal = self.calculate_signal(symbol, price)
        
        if signal != 0:
            # Generate signal event
            signal_event = SignalEvent(
                symbol=symbol,
                signal_type=SignalType.LONG if signal > 0 else SignalType.SHORT,
                strength=abs(signal)
            )
            self.context.event_bus.publish(signal_event)
    
    def on_fill_event(self, event: FillEvent):
        """Handle order fills"""
        self.logger.info(f"Filled: {event}")
        
    def calculate_signal(self, symbol, price):
        """Your alpha generation logic"""
        # Implement your strategy logic
        return 0
```

### Configuring Risk Limits

```python
from platform.risk.limits import RiskLimit, LimitType

# Define risk limits
limits = [
    RiskLimit(
        name='max_position_size',
        limit_type=LimitType.POSITION_SIZE,
        value=0.05,  # 5% of portfolio per position
        scope='symbol'
    ),
    RiskLimit(
        name='max_leverage',
        limit_type=LimitType.LEVERAGE,
        value=2.0,  # 2x leverage
        scope='portfolio'
    ),
    RiskLimit(
        name='max_sector_exposure',
        limit_type=LimitType.SECTOR_EXPOSURE,
        value=0.25,  # 25% per sector
        scope='sector'
    )
]

# Apply to engine
engine.risk_manager.add_limits(limits)
```

## Component Details

### Event System

The event system is the backbone of the platform. All components communicate through events:

```python
# Publishing an event
event = MarketEvent(
    timestamp=datetime.now(),
    symbol='AAPL',
    open=150.0,
    high=152.0,
    low=149.5,
    close=151.5,
    volume=1000000
)
event_bus.publish(event)

# Subscribing to events
def handle_market_event(event: MarketEvent):
    print(f"Received: {event}")

event_bus.subscribe(MarketEvent, handle_market_event)
```

### Data Management

Access historical and live data through the DataManager:

```python
from platform.data.manager import DataManager
from datetime import datetime

data_manager = DataManager()

# Get historical bars
bars = data_manager.get_bars(
    symbols=['AAPL', 'GOOGL'],
    start_date=datetime(2023, 1, 1),
    end_date=datetime(2023, 12, 31),
    frequency='1D'
)

# Subscribe to live data
data_manager.subscribe_live(
    symbols=['AAPL'],
    callback=my_callback
)
```

## Configuration

Configuration is managed through YAML files in the `config/` directory:

### System Configuration (config/system.yaml)

```yaml
database:
  host: localhost
  port: 5432
  name: trading_platform
  user: trader
  
redis:
  host: localhost
  port: 6379
  
logging:
  level: INFO
  file: logs/platform.log
```

### Strategy Configuration (config/strategies/momentum.yaml)

```yaml
strategy:
  name: MomentumStrategy
  class: strategies.examples.momentum.MomentumStrategy
  
parameters:
  lookback_period: 20
  top_n: 10
  rebalance_frequency: weekly
  
universe:
  asset_class: equity
  min_market_cap: 1000000000
  min_liquidity: 1000000
  
risk:
  max_position_size: 0.05
  max_leverage: 1.5
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run with coverage
pytest --cov=src/platform --cov-report=html

# Run specific test file
pytest tests/unit/test_strategy.py
```

### Test Structure

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **Regression Tests**: Ensure backtest results reproduce exactly

## Deployment

### Development Environment

```bash
# Activate virtual environment
source venv/bin/activate

# Run backtest
python scripts/backtest.py --config config/strategies/momentum.yaml

# Start Jupyter for research
jupyter notebook
```

### Production Deployment

```bash
# Build Docker image
docker build -t trading-platform:latest .

# Deploy with docker-compose
docker-compose -f docker-compose.prod.yml up -d

# Monitor logs
docker-compose logs -f platform

# Check system health
curl http://localhost:8000/health
```

### Monitoring

The platform includes built-in monitoring:

- Real-time PnL dashboard (http://localhost:8000/dashboard)
- Prometheus metrics endpoint (http://localhost:8000/metrics)
- Slack/email alerts for risk breaches
- Daily reconciliation reports

## Technology Stack

### Core Libraries
- **pandas** - Data manipulation and time-series
- **numpy** - Numerical computations
- **pydantic** - Data validation and settings
- **asyncio** - Asynchronous operations
- **SQLAlchemy** - Database ORM

### Data Science
- **scipy** - Statistical functions
- **statsmodels** - Time-series analysis
- **scikit-learn** - Machine learning
- **cvxpy** - Portfolio optimization

### Visualization
- **matplotlib** - Basic plotting
- **plotly** - Interactive dashboards
- **quantstats** - Trading analytics

### Infrastructure
- **PostgreSQL** - Primary database
- **Redis** - Caching and pub/sub
- **TimescaleDB** - Time-series data
- **Docker** - Containerization

## Roadmap

### Phase 1: Foundation ✅
- Core event system
- Data management framework
- Basic strategy interface
- Simulated broker

### Phase 2: Backtesting (In Progress)
- Backtest engine implementation
- Portfolio and position tracking
- Analytics and reporting
- Example strategies

### Phase 3: Risk and Execution
- Risk management framework
- Advanced order types
- Transaction cost models
- Broker integration

### Phase 4: Production
- Comprehensive testing
- Monitoring and alerting
- Documentation
- Performance optimization

### Phase 5: Enhancement
- Machine learning integration
- Real-time optimization
- Multi-strategy coordination
- Advanced portfolio construction

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass (`pytest`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

## Support

- Documentation: [https://docs.tradingplatform.dev](https://docs.tradingplatform.dev)
- Issues: [GitHub Issues](https://github.com/yourorg/trading_platform/issues)
- Discussions: [GitHub Discussions](https://github.com/yourorg/trading_platform/discussions)
- Email: support@tradingplatform.dev

## Acknowledgments

Built with inspiration from:
- Zipline (Quantopian)
- Backtrader
- PyAlgoTrade
- QuantConnect LEAN

---

**Disclaimer**: This software is for educational and research purposes. Use at your own risk. Past performance does not guarantee future results. Always test strategies thoroughly before deploying capital.
