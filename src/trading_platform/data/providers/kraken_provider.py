"""
Kraken data provider using the Kraken REST API v1.

Supports OHLC bars, limit order books, recent trades, ticker quotes,
and spread data via public endpoints.  Private endpoints (account balance,
trade history, open positions) require a Kraken API key + secret.

Configuration keys (passed as a dict to __init__):
    kraken_api_key     – Kraken API key (private endpoints only)
    kraken_api_secret  – Kraken API secret, base64-encoded (private endpoints only)
    cache_dir          – directory for parquet cache (default: 'data/cache')
"""
import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from ...core.types import Symbol

logger = __import__('logging').getLogger(__name__)

_BASE_URL = "https://api.kraken.com"

# Kraken OHLC interval is specified in minutes
_FREQ_TO_INTERVAL: Dict[str, int] = {
    '1m':  1,
    '5m':  5,
    '15m': 15,
    '30m': 30,
    '1h':  60,
    '4h':  240,
    '1D':  1440,
    '1W':  10080,
}

# Conventional symbol remaps → Kraken pair names
_PAIR_REMAP: Dict[str, str] = {
    'BTC/USD': 'XBTUSD', 'BTC-USD': 'XBTUSD', 'BTCUSD': 'XBTUSD',
    'BTC/EUR': 'XBTEUR', 'BTC-EUR': 'XBTEUR', 'BTCEUR': 'XBTEUR',
    'BTC':     'XXBT',
}


class KrakenDataProvider:
    """
    Fetch market data from Kraken via the REST API.

    Public endpoints (no auth required):
      load_data()       – OHLCV bars; satisfies the DataManager provider interface
      get_order_book()  – full limit order book snapshot
      get_trades()      – recent or historical trade list
      get_ticker()      – current bid/ask/last/volume for one or more pairs
      get_spread()      – recent spread (bid/ask) time series
      get_asset_pairs() – metadata for all tradeable pairs

    Private endpoints (require kraken_api_key + kraken_api_secret):
      get_account_balance()  – asset balances
      get_trade_history()    – personal fills
      get_open_positions()   – open margin positions
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.api_key: Optional[str] = (
            cfg.get('kraken_api_key') or os.environ.get('KRAKEN_API_KEY')
        )
        self.api_secret: Optional[str] = (
            cfg.get('kraken_api_secret') or os.environ.get('KRAKEN_API_SECRET')
        )
        cache_root = cfg.get('cache_dir', 'data/cache')
        self.cache_dir: Optional[Path] = Path(cache_root) if cache_root else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': 'trading-platform/0.1'})

    # ------------------------------------------------------------------
    # Public market data
    # ------------------------------------------------------------------

    def load_data(
        self,
        symbols: List[Symbol],
        start_date: datetime,
        end_date: datetime,
        frequency: str = '1D',
    ) -> Dict[str, pd.DataFrame]:
        """
        Load OHLCV bars for the given symbols and date range.

        Matches the interface expected by DataManager so 'kraken' can be
        specified as the provider in config.

        Returns:
            Dict mapping symbol → DataFrame with columns
            [Open, High, Low, Close, Volume, Vwap, Trades] and a
            timezone-naive datetime index named 'Date'.
        """
        data: Dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            df = self._load_from_cache(symbol, start_date, end_date, frequency)
            if df is None:
                df = self._fetch_ohlc(symbol, start_date, end_date, frequency)
                if df is not None and not df.empty:
                    self._save_to_cache(symbol, start_date, end_date, df, frequency)
            if df is not None and not df.empty:
                data[symbol] = df
            else:
                logger.warning("No OHLC data loaded for %s", symbol)
        logger.info(
            "Kraken provider loaded OHLCV for %d/%d symbols at %s",
            len(data), len(symbols), frequency,
        )
        return data

    def get_order_book(
        self,
        symbol: str,
        depth: int = 10,
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch a limit order book snapshot.

        Args:
            symbol: Kraken pair (e.g. 'XBTUSD') or conventional name ('BTC/USD').
            depth:  Number of price levels per side (1–500, default 10).

        Returns:
            Dict with 'bids' and 'asks' keys.  Each value is a DataFrame
            with columns [price, volume, timestamp] sorted best-to-worst.
        """
        pair = _to_kraken_pair(symbol)
        result = self._public_get('/0/public/Depth', {
            'pair': pair,
            'count': min(max(depth, 1), 500),
        })
        if result is None:
            return {}

        raw = result[_first_key(result)]
        out: Dict[str, pd.DataFrame] = {}
        for side in ('bids', 'asks'):
            df = pd.DataFrame(raw[side], columns=['price', 'volume', 'timestamp'])
            df['price'] = df['price'].astype(float)
            df['volume'] = df['volume'].astype(float)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            out[side] = df

        logger.info(
            "Order book for %s: %d bids, %d asks",
            symbol, len(out['bids']), len(out['asks']),
        )
        return out

    def get_trades(
        self,
        symbol: str,
        since: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Fetch recent public trades.

        Args:
            symbol: Kraken pair or conventional name.
            since:  Return trades at or after this time (optional).

        Returns:
            DataFrame with columns [price, volume, time, side, order_type]
            where side ∈ {'buy', 'sell'} and order_type ∈ {'market', 'limit'}.
        """
        pair = _to_kraken_pair(symbol)
        params: Dict[str, Any] = {'pair': pair}
        if since is not None:
            # Kraken 'since' for Trades is nanoseconds
            params['since'] = int(since.timestamp() * 1e9)

        result = self._public_get('/0/public/Trades', params)
        if result is None:
            return pd.DataFrame()

        rows = result[_first_key(result)]
        # Kraken added trade_id as a 7th field; handle both old (6-col) and new (7-col) format
        n_cols = len(rows[0]) if rows else 6
        base_cols = ['price', 'volume', 'time', 'side', 'order_type', 'misc']
        cols = base_cols + (['trade_id'] if n_cols > 6 else [])
        df = pd.DataFrame(rows, columns=cols)
        df['price'] = df['price'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df['side'] = df['side'].map({'b': 'buy', 's': 'sell'})
        df['order_type'] = df['order_type'].map({'m': 'market', 'l': 'limit'})
        df = df.drop(columns=['misc'])

        logger.info("Fetched %d trades for %s", len(df), symbol)
        return df

    def get_ticker(self, symbols: List[str]) -> pd.DataFrame:
        """
        Fetch current ticker for one or more pairs.

        Returns:
            DataFrame indexed by Kraken pair name with columns:
            ask, ask_size, bid, bid_size, last_price, last_volume,
            vwap_today, vwap_24h, volume_today, volume_24h,
            trades_today, trades_24h, open, high, low.
        """
        pair = ','.join(_to_kraken_pair(s) for s in symbols)
        result = self._public_get('/0/public/Ticker', {'pair': pair})
        if result is None:
            return pd.DataFrame()

        rows = {}
        for raw_pair, v in result.items():
            rows[raw_pair] = {
                'ask':          float(v['a'][0]),
                'ask_size':     float(v['a'][2]),
                'bid':          float(v['b'][0]),
                'bid_size':     float(v['b'][2]),
                'last_price':   float(v['c'][0]),
                'last_volume':  float(v['c'][1]),
                'vwap_today':   float(v['p'][0]),
                'vwap_24h':     float(v['p'][1]),
                'volume_today': float(v['v'][0]),
                'volume_24h':   float(v['v'][1]),
                'trades_today': int(v['t'][0]),
                'trades_24h':   int(v['t'][1]),
                'open':         float(v['o']),
                'high':         float(v['h'][1]),
                'low':          float(v['l'][1]),
            }
        df = pd.DataFrame(rows).T
        logger.info("Fetched ticker for %d pairs", len(df))
        return df

    def get_spread(
        self,
        symbol: str,
        since: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Fetch recent bid/ask spread time series.

        Args:
            symbol: Kraken pair or conventional name.
            since:  Fetch data since this time (optional).

        Returns:
            DataFrame with columns [timestamp, bid, ask] in UTC.
        """
        pair = _to_kraken_pair(symbol)
        params: Dict[str, Any] = {'pair': pair}
        if since is not None:
            params['since'] = int(since.timestamp())

        result = self._public_get('/0/public/Spread', params)
        if result is None:
            return pd.DataFrame()

        df = pd.DataFrame(result[_first_key(result)], columns=['timestamp', 'bid', 'ask'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
        df['bid'] = df['bid'].astype(float)
        df['ask'] = df['ask'].astype(float)

        logger.info("Fetched %d spread entries for %s", len(df), symbol)
        return df

    def get_asset_pairs(self) -> pd.DataFrame:
        """
        List all available trading pairs with their metadata.

        Useful for discovering valid pair names before requesting data.
        Returns a DataFrame indexed by Kraken pair name.
        """
        result = self._public_get('/0/public/AssetPairs', {})
        if result is None:
            return pd.DataFrame()
        df = pd.DataFrame(result).T
        logger.info("Fetched %d asset pairs from Kraken", len(df))
        return df

    # ------------------------------------------------------------------
    # Private (authenticated) endpoints
    # ------------------------------------------------------------------

    def get_account_balance(self) -> Dict[str, float]:
        """
        Return asset balances for the authenticated account.

        Returns:
            Dict mapping asset name (e.g. 'XXBT', 'ZUSD') to balance.
        """
        self._require_auth()
        result = self._private_post('/0/private/Balance', {})
        if result is None:
            return {}
        return {k: float(v) for k, v in result.items()}

    def get_trade_history(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        trade_type: str = 'all',
    ) -> pd.DataFrame:
        """
        Fetch personal trade history.

        Args:
            start:      Filter to trades at or after this time.
            end:        Filter to trades at or before this time.
            trade_type: 'all' | 'any position' | 'closed position' |
                        'closing position' | 'no position'

        Returns:
            DataFrame of fills; 'time' column is UTC-aware datetime.
        """
        self._require_auth()
        params: Dict[str, Any] = {'type': trade_type}
        if start:
            params['start'] = int(start.timestamp())
        if end:
            params['end'] = int(end.timestamp())

        result = self._private_post('/0/private/TradesHistory', params)
        if result is None or 'trades' not in result:
            return pd.DataFrame()

        df = pd.DataFrame(result['trades']).T
        if not df.empty and 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        return df

    def get_open_positions(self) -> pd.DataFrame:
        """
        Return open margin positions for the authenticated account.

        Returns:
            DataFrame indexed by position ID.
        """
        self._require_auth()
        result = self._private_post('/0/private/OpenPositions', {})
        if result is None:
            return pd.DataFrame()
        return pd.DataFrame(result).T

    # ------------------------------------------------------------------
    # Internal helpers – OHLC download + pagination
    # ------------------------------------------------------------------

    def _fetch_ohlc(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        frequency: str,
    ) -> Optional[pd.DataFrame]:
        """Download and paginate OHLCV bars from Kraken."""
        interval = _FREQ_TO_INTERVAL.get(frequency, 1440)
        pair = _to_kraken_pair(symbol)
        since = int(start_date.timestamp())
        end_ts = int(end_date.timestamp())

        all_bars: List = []
        while True:
            result = self._public_get('/0/public/OHLC', {
                'pair': pair, 'interval': interval, 'since': since,
            })
            if result is None:
                break

            bars = result[_first_key(result)]
            if not bars:
                break

            all_bars.extend(bars)
            last_ts = int(result.get('last', 0))

            if last_ts == 0 or last_ts >= end_ts:
                break
            since = last_ts  # Kraken pagination: advance cursor
            time.sleep(1)    # avoid rate-limiting between pages

        if not all_bars:
            logger.warning("Kraken returned no OHLC for %s at %s", symbol, frequency)
            return None

        df = pd.DataFrame(all_bars, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count',
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df = df.set_index('timestamp')
        df.index.name = 'Date'

        for col in ('open', 'high', 'low', 'close', 'vwap', 'volume'):
            df[col] = df[col].astype(float)
        df['count'] = df['count'].astype(int)

        df = df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'vwap': 'Vwap', 'volume': 'Volume',
            'count': 'Trades',
        })
        df = df[~df.index.duplicated(keep='last')].sort_index()
        df = df.loc[start_date:end_date]

        logger.info("Downloaded %d OHLC bars for %s at %s", len(df), symbol, frequency)
        return df

    # ------------------------------------------------------------------
    # Internal helpers – HTTP
    # ------------------------------------------------------------------

    def _public_get(
        self, path: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            resp = self._session.get(_BASE_URL + path, params=params, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            if body.get('error'):
                logger.error("Kraken API error (%s): %s", path, body['error'])
                return None
            return body.get('result')
        except Exception as exc:
            logger.error("Kraken GET failed (%s): %s", path, exc)
            return None

    def _private_post(
        self, path: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        nonce = str(int(time.time() * 1000))
        data['nonce'] = nonce
        post_data = urllib.parse.urlencode(data)

        # Signature: HMAC-SHA512(path + SHA256(nonce + post_data), secret)
        message = path.encode() + hashlib.sha256(
            (nonce + post_data).encode()
        ).digest()
        secret_bytes = base64.b64decode(self.api_secret)  # type: ignore[arg-type]
        sig = base64.b64encode(
            hmac.new(secret_bytes, message, hashlib.sha512).digest()
        ).decode()

        try:
            resp = self._session.post(
                _BASE_URL + path,
                data=data,
                headers={'API-Key': self.api_key, 'API-Sign': sig},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get('error'):
                logger.error("Kraken private API error (%s): %s", path, body['error'])
                return None
            return body.get('result')
        except Exception as exc:
            logger.error("Kraken POST failed (%s): %s", path, exc)
            return None

    def _require_auth(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "kraken_api_key and kraken_api_secret must be set in config "
                "to use private Kraken endpoints."
            )

    # ------------------------------------------------------------------
    # Internal helpers – caching
    # ------------------------------------------------------------------

    def _cache_path(
        self, symbol: str, start_date: datetime, end_date: datetime, frequency: str
    ) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        freq_str = frequency.replace('/', '')
        return self.cache_dir / (
            f"kraken_{symbol}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_{freq_str}.parquet"
        )

    def _load_from_cache(
        self, symbol: str, start_date: datetime, end_date: datetime, frequency: str
    ) -> Optional[pd.DataFrame]:
        path = self._cache_path(symbol, start_date, end_date, frequency)
        if path is None or not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            logger.info("Loaded %d bars for %s from cache", len(df), symbol)
            return df
        except Exception as exc:
            logger.warning("Cache read failed for %s: %s", symbol, exc)
            return None

    def _save_to_cache(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        df: pd.DataFrame,
        frequency: str,
    ) -> None:
        path = self._cache_path(symbol, start_date, end_date, frequency)
        if path is None:
            return
        try:
            df.to_parquet(path)
            logger.debug("Cached %s OHLC to %s", symbol, path)
        except Exception as exc:
            logger.warning("Cache write failed for %s: %s", symbol, exc)


# ------------------------------------------------------------------
# Module-level utilities
# ------------------------------------------------------------------

def _to_kraken_pair(symbol: str) -> str:
    """
    Convert a symbol to a Kraken pair string.

    Handles conventional names like 'BTC/USD', 'BTC-USD', 'BTCUSD'.
    Falls back to stripping separators and upper-casing.
    """
    upper = symbol.upper()
    if upper in _PAIR_REMAP:
        return _PAIR_REMAP[upper]
    stripped = upper.replace('/', '').replace('-', '').replace('_', '')
    return _PAIR_REMAP.get(stripped, stripped)


def _first_key(d: Dict) -> str:
    """Return the first key of a dict (Kraken returns pair-keyed results)."""
    return next(iter(d))
