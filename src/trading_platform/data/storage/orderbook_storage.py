"""
Parquet-backed storage for limit order book snapshots.

Layout on disk::

    {base_dir}/{symbol}/{YYYY-MM-DD}.parquet

Schema per file (one row = one price level at one point in time)::

    timestamp  | datetime64[ns, UTC]
    symbol     | string
    side       | string  ('bid' | 'ask')
    price      | float64
    qty        | float64
    level      | int64   (0 = best)

Snapshots are buffered in memory and flushed to disk when the buffer
exceeds ``buffer_size`` rows, when ``flush()`` is called explicitly, or
when the object is garbage-collected.

The interval between stored snapshots per symbol is throttled by
``snapshot_interval`` (default 1 s) to avoid storing every tick.

Loading::

    df = storage.load("BTC/USD", start_dt, end_dt)
    # group by timestamp to reconstruct the book at each point in time:
    for ts, book in df.groupby("timestamp"):
        bids = book[book.side == "bid"].sort_values("level")
        asks = book[book.side == "ask"].sort_values("level")
"""
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class OrderBookStorage:
    """
    Persist and retrieve order book snapshots as Parquet files.

    Args:
        base_dir:          Root directory; sub-dirs are created per symbol.
        buffer_size:       Row count that triggers an automatic flush (default 10 000).
        snapshot_interval: Minimum seconds between stored snapshots per symbol (default 1.0).
    """

    def __init__(
        self,
        base_dir: str,
        buffer_size: int = 10_000,
        snapshot_interval: float = 1.0,
    ):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.buffer_size = buffer_size
        self.snapshot_interval = snapshot_interval

        self._buffer: Dict[str, List[dict]] = defaultdict(list)
        self._last_ts: Dict[str, Optional[datetime]] = defaultdict(lambda: None)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record_snapshot(
        self,
        symbol: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        timestamp: datetime,
    ) -> None:
        """
        Buffer a full order book snapshot for later persistence.

        ``bids`` and ``asks`` should each be a list of (price, qty) tuples
        sorted best-first (highest bid / lowest ask first).

        Calls with the same symbol within ``snapshot_interval`` seconds are
        silently dropped to avoid storing every tick.
        """
        with self._lock:
            last = self._last_ts[symbol]
            if last is not None:
                elapsed = (timestamp - last).total_seconds()
                if elapsed < self.snapshot_interval:
                    return
            self._last_ts[symbol] = timestamp

            for level, (price, qty) in enumerate(bids):
                self._buffer[symbol].append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "side": "bid",
                    "price": price,
                    "qty": qty,
                    "level": level,
                })
            for level, (price, qty) in enumerate(asks):
                self._buffer[symbol].append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "side": "ask",
                    "price": price,
                    "qty": qty,
                    "level": level,
                })

            buf_size = len(self._buffer[symbol])

        if buf_size >= self.buffer_size:
            self.flush(symbol)

    def flush(self, symbol: Optional[str] = None) -> None:
        """
        Write all buffered rows to Parquet files.

        Args:
            symbol: Flush only this symbol; flush all symbols if None.
        """
        with self._lock:
            if symbol:
                targets = {symbol: self._buffer.pop(symbol, [])}
            else:
                targets = dict(self._buffer)
                self._buffer.clear()

        for sym, rows in targets.items():
            if rows:
                self._write(sym, rows)

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def load(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """
        Load stored snapshots for a symbol within a date range.

        Returns a DataFrame with columns
        [timestamp, symbol, side, price, qty, level] sorted by timestamp.

        To reconstruct the book at a specific time::

            snap = df[df.timestamp == df.timestamp.unique()[i]]
            bids = snap[snap.side == "bid"].sort_values("level")
            asks = snap[snap.side == "ask"].sort_values("level")
        """
        sym_dir = self.base_dir / _safe_dirname(symbol)
        if not sym_dir.exists():
            logger.warning("No stored data for %s at %s", symbol, sym_dir)
            return pd.DataFrame()

        frames = []
        for path in sorted(sym_dir.glob("*.parquet")):
            file_date = _stem_to_date(path.stem)
            if file_date is None:
                continue
            if not (start_date.date() <= file_date <= end_date.date()):
                continue
            try:
                frames.append(pd.read_parquet(path))
            except Exception as exc:
                logger.warning("Skipping unreadable file %s: %s", path, exc)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        mask = (df["timestamp"] >= pd.Timestamp(start_date, tz="UTC")) & \
               (df["timestamp"] <= pd.Timestamp(end_date, tz="UTC"))
        return df[mask].sort_values("timestamp").reset_index(drop=True)

    def available_symbols(self) -> List[str]:
        """Return symbols that have data on disk."""
        return [d.name for d in self.base_dir.iterdir() if d.is_dir()]

    def date_range(self, symbol: str) -> Tuple[Optional[date], Optional[date]]:
        """Return (earliest_date, latest_date) stored for a symbol, or (None, None)."""
        sym_dir = self.base_dir / _safe_dirname(symbol)
        dates = [
            _stem_to_date(p.stem)
            for p in sym_dir.glob("*.parquet")
            if _stem_to_date(p.stem) is not None
        ]
        if not dates:
            return None, None
        return min(dates), max(dates)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, symbol: str, rows: List[dict]) -> None:
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        sym_dir = self.base_dir / _safe_dirname(symbol)
        sym_dir.mkdir(parents=True, exist_ok=True)

        # Group by calendar day and write/append one file per day
        for day, group in df.groupby(df["timestamp"].dt.date):
            path = sym_dir / f"{day}.parquet"
            if path.exists():
                try:
                    existing = pd.read_parquet(path)
                    group = pd.concat([existing, group], ignore_index=True)
                    group = group.drop_duplicates(
                        subset=["timestamp", "side", "price"], keep="last"
                    )
                except Exception as exc:
                    logger.warning("Could not read existing file %s: %s", path, exc)
            group = group.sort_values("timestamp")
            group.to_parquet(path, index=False)
            logger.debug("Wrote %d rows to %s", len(group), path)

    def __del__(self) -> None:
        """Flush any remaining buffered data on garbage collection."""
        try:
            self.flush()
        except Exception:
            pass


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _safe_dirname(symbol: str) -> str:
    """Convert a symbol like 'BTC/USD' to a filesystem-safe name 'BTC_USD'."""
    return symbol.replace("/", "_").replace("\\", "_")


def _stem_to_date(stem: str) -> Optional[date]:
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None
