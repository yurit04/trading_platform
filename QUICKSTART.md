# Quick Start Guide

This guide will help you get started with the trading platform in minutes.

## Installation

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/yurit04/trading_platform.git
cd trading_platform

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env  # or use your preferred editor
```

## Running Your First Backtest

### Option 1: Using the Example Strategy

```python
# Create a simple backtest script
from datetime import datetime
from platform.core.engine import BacktestEngine
from strategies.examples.momentum import MomentumStrategy

# Define universe
universe = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META']

# Create strategy
strategy = MomentumStrategy(
    universe=universe,
    lookback_period=20,
    top_n=3
)

# Create backtest engine
engine = BacktestEngine(
    start_date=datetime(2020, 1, 1),
    end_date=datetime(2023, 12, 31),
    initial_capital=1_000_000
)

# Add strategy and run
engine.add_strategy(strategy)
engine.initialize()
results = engine.start()

# Print results
print(f"Total Return: {results['total_return']:.2%}")
print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {results['max_drawdown']:.2%}")
```

### Option 2: Using Configuration File

```bash
# Run backtest with configuration
python scripts/backtest.py --config config/strategies/momentum.yaml

# Or with command line parameters
python scripts/backtest.py \
    --strategy momentum \
    --start 2020-01-01 \
    --end 2023-12-31 \
    --capital 1000000
```

## Creating Your Own Strategy

### 1. Create Strategy File

Create a new file in `strategies/examples/my_strategy.py`:

```python
from typing import List
from platform.strategy.base import Strategy
from platform.core.event import MarketEvent, FillEvent
from platform.core.types import Symbol

class MyStrategy(Strategy):
    """Your custom strategy."""
    
    def __init__(self, universe: List[Symbol]):
        super().__init__("MyStrategy")
        self.universe = universe
    
    def on_initialize(self):
        """Initialize strategy."""
        self.logger.info("Strategy initialized")
    
    def on_market_event(self, event: MarketEvent):
        """Handle market data."""
        # Your strategy logic here
        pass
    
    def on_fill_event(self, event: FillEvent):
        """Handle order fills."""
        self.logger.info(f"Order filled: {event}")
    
    def get_universe(self) -> List[Symbol]:
        """Return trading universe."""
        return self.universe
```

### 2. Create Configuration

Create `config/strategies/my_strategy.yaml`:

```yaml
strategy:
  name: MyStrategy
  class: strategies.examples.my_strategy.MyStrategy

parameters:
  # Your parameters here

universe:
  symbols:
    - AAPL
    - MSFT
    - GOOGL

risk:
  max_position_size: 0.10
  max_leverage: 1.0
```

### 3. Run Your Strategy

```bash
python scripts/backtest.py --config config/strategies/my_strategy.yaml
```

## Using Docker

### 1. Build and Run

```bash
# Build the image
docker-compose build

# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f platform

# Run a backtest
docker-compose exec platform python scripts/backtest.py \
    --config config/strategies/momentum.yaml
```

### 2. Access Jupyter

```bash
# Jupyter will be available at http://localhost:8888
docker-compose up jupyter

# Open browser to http://localhost:8888
```

## Testing

### Run All Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/platform

# Run specific test file
pytest tests/unit/test_event.py

# Run with verbose output
pytest -v
```

## Next Steps

### 1. Explore Examples

Look at the example strategies in `strategies/examples/`:
- `momentum.py` - Momentum-based strategy
- `mean_reversion.py` - Mean reversion strategy (to be implemented)
- `pairs_trading.py` - Pairs trading strategy (to be implemented)

### 2. Read Documentation

- Full documentation: [docs/README.md](docs/README.md)
- API Reference: [docs/api/README.md](docs/api/README.md)
- Strategy Development: [docs/strategy_development.md](docs/strategy_development.md)

### 3. Configure Data Sources

Set up your data providers in `config/data_providers/`:
- Polygon.io for market data
- CryptoCompare for crypto data
- Custom CSV files

### 4. Set Up Brokers (for live trading)

Configure broker connections in `config/brokers/`:
- Interactive Brokers
- Alpaca
- Binance (crypto)
- Coinbase (crypto)

## Common Issues

### Import Errors

Make sure you've installed the package:
```bash
pip install -e .
```

### Data Not Available

If backtest fails due to missing data:
```bash
# Download historical data
python scripts/data_download.py --symbols AAPL MSFT --start 2020-01-01
```

### Database Connection

If database connection fails:
```bash
# Start database with Docker
docker-compose up -d postgres timescaledb redis
```

## Getting Help

- GitHub Issues: [https://github.com/yurit04/trading_platform/issues](https://github.com/yurit04/trading_platform/issues)
- Documentation: [https://docs.tradingplatform.dev](https://docs.tradingplatform.dev)
- Discussions: [https://github.com/yurit04/trading_platform/discussions](https://github.com/yurit04/trading_platform/discussions)

## What's Next?

1. **Learn the Architecture**: Read the [Architecture Guide](docs/architecture.md)
2. **Develop Strategies**: Check out the [Strategy Development Guide](docs/strategy_development.md)
3. **Optimize Performance**: See [Performance Tuning](docs/performance.md)
4. **Deploy to Production**: Follow the [Deployment Guide](docs/deployment.md)

Happy trading!
