# Installation and Setup Guide

## Quick Installation

### Prerequisites
- Python 3.10 or higher
- PostgreSQL 14+ (optional, for production)
- Redis 6+ (optional, for caching)
- Docker (optional, for containerized deployment)

### Basic Setup

1. **Clone and navigate to the directory**
   ```bash
   cd trading_platform
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Create necessary directories**
   ```bash
   mkdir -p data/{historical,reference,cache} logs results/{backtests,reports}
   ```

## Verification

Test your installation:

```python
python -c "from platform.core.engine import BacktestEngine; print('✓ Installation successful!')"
```

## Next Steps

1. Read `QUICKSTART.md` for your first backtest
2. Review `README.md` for full documentation
3. Check `PROJECT_SUMMARY.md` for implementation status

## Docker Installation (Alternative)

If you prefer Docker:

```bash
docker-compose up -d
docker-compose exec platform python -c "from platform.core.engine import BacktestEngine; print('✓ Docker installation successful!')"
```

## Troubleshooting

### Import Errors
Make sure you've installed the package:
```bash
pip install -e .
```

### Module Not Found
Ensure you're in the virtual environment:
```bash
source venv/bin/activate
```

### Permission Errors
Check directory permissions:
```bash
chmod -R 755 data logs results
```

## Support

For issues, see PROJECT_SUMMARY.md or README.md for contact information.
