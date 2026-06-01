#!/usr/bin/env python3
"""
Download OHLC bars for Kraken tradeable pairs and store as Parquet files.

Storage layout::

    {output_dir}/{frequency}/{pair}.parquet
    e.g.  data/kraken/1D/XBTUSD.parquet
          data/kraken/1h/ETHUSD.parquet

Backfill behaviour:
    If a file already exists the script reads the latest bar timestamp it
    contains and downloads only the bars from that point to now.  Re-running
    the script therefore acts as an incremental update with no duplicates.

Examples::

    # Download everything (all online pairs, all frequencies)
    python scripts/kraken_bars.py data/kraken

    # USD pairs only, daily + hourly bars
    python scripts/kraken_bars.py data/kraken --quote USD --frequencies 1D 1h

    # Specific pairs only
    python scripts/kraken_bars.py data/kraken --pairs XBTUSD ETHUSD SOLUSD

    # Faster: 3 parallel workers (Kraken burst limit is ~15 req; 3/s is safe)
    python scripts/kraken_bars.py data/kraken --quote USD --workers 3

    # Preview what would run without downloading anything
    python scripts/kraken_bars.py data/kraken --quote USD --dry-run
"""
import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / 'src'))

from trading_platform.data.providers.kraken_provider import KrakenDataProvider
from trading_platform.utils.logging import setup_logging

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # fall back to plain logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All frequencies Kraken's OHLC endpoint supports, ordered fastest → slowest.
ALL_FREQUENCIES = ['1m', '5m', '15m', '30m', '1h', '4h', '1D', '1W']

# Earliest date Kraken has data for (Sep 2013 launch).
_KRAKEN_EPOCH = datetime(2013, 9, 1, tzinfo=timezone.utc)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Thread-safe rate limiter — enforces a minimum gap between calls."""

    def __init__(self, calls_per_second: float = 1.0):
        self._min_interval = 1.0 / calls_per_second
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


# ---------------------------------------------------------------------------
# Per-task result
# ---------------------------------------------------------------------------

@dataclass
class _Result:
    pair: str
    frequency: str
    status: str          # 'new' | 'updated' | 'skipped' | 'failed'
    bars_added: int = 0
    since: Optional[datetime] = None
    error: str = ''


# ---------------------------------------------------------------------------
# Parquet helpers
# ---------------------------------------------------------------------------

def _parquet_path(output_dir: Path, frequency: str, pair: str) -> Path:
    return output_dir / frequency / f"{pair}.parquet"


def _last_timestamp(path: Path) -> Optional[datetime]:
    """Return the newest bar timestamp in an existing parquet file."""
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=[])  # index only
        if df.index.empty:
            return None
        ts = df.index.max()
        # Ensure UTC-aware for comparison
        if hasattr(ts, 'tzinfo') and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None


def _save(path: Path, df_new: pd.DataFrame) -> int:
    """
    Append df_new to an existing parquet file (or create it).

    Deduplicates on the timestamp index, keeping the latest version of each
    bar (so partially-complete bars from a previous run get overwritten).

    Returns the number of net-new bars written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            df_existing = pd.read_parquet(path)
            combined = pd.concat([df_existing, df_new])
            combined = combined[~combined.index.duplicated(keep='last')]
            combined.sort_index(inplace=True)
            net_new = len(combined) - len(df_existing)
        except Exception as exc:
            logger.warning("Could not merge with %s (%s); overwriting.", path, exc)
            combined = df_new.sort_index()
            net_new = len(combined)
    else:
        combined = df_new.sort_index()
        net_new = len(combined)

    combined.to_parquet(path)
    return max(net_new, 0)


# ---------------------------------------------------------------------------
# Single download task
# ---------------------------------------------------------------------------

def _download_one(
    provider: KrakenDataProvider,
    pair: str,
    frequency: str,
    output_dir: Path,
    rate_limiter: _RateLimiter,
) -> _Result:
    path = _parquet_path(output_dir, frequency, pair)
    last_ts = _last_timestamp(path)

    # Start just before the last known bar so any incomplete bar is refreshed
    since = last_ts if last_ts is not None else _KRAKEN_EPOCH
    now = datetime.now(timezone.utc)

    if since >= now:
        return _Result(pair, frequency, 'skipped', since=since)

    rate_limiter.acquire()
    try:
        # _fetch_ohlc is internal but this script is part of the same project
        df = provider._fetch_ohlc(pair, since, now, frequency)
    except Exception as exc:
        return _Result(pair, frequency, 'failed', error=str(exc))

    if df is None or df.empty:
        return _Result(pair, frequency, 'skipped', since=since)

    try:
        bars_added = _save(path, df)
    except Exception as exc:
        return _Result(pair, frequency, 'failed', error=f"save failed: {exc}")

    status = 'updated' if last_ts is not None else 'new'
    return _Result(pair, frequency, status, bars_added=bars_added, since=since)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Download Kraken OHLC bars for all (or filtered) tradeable pairs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'output_dir',
        help='Directory to store Parquet files  (e.g. data/kraken)',
    )
    parser.add_argument(
        '--quote',
        metavar='CURRENCY',
        help='Only download pairs quoted in this currency, e.g. USD, EUR, USDT, BTC',
    )
    parser.add_argument(
        '--frequencies',
        nargs='+',
        metavar='FREQ',
        default=ALL_FREQUENCIES,
        choices=ALL_FREQUENCIES,
        help=(
            'Frequencies to download (default: all). '
            f'Choices: {" ".join(ALL_FREQUENCIES)}'
        ),
    )
    parser.add_argument(
        '--pairs',
        nargs='+',
        metavar='PAIR',
        help='Specific Kraken pair IDs to download, e.g. XBTUSD ETHUSD',
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        metavar='N',
        help='Parallel download workers (default: 1).  Max ~3 to stay within Kraken rate limits.',
    )
    parser.add_argument(
        '--rate',
        type=float,
        default=0.5,
        metavar='REQ/S',
        help='Max API requests per second (default: 0.5).  Kraken public limit is ~1/s sustained.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print what would be downloaded without making any API calls.',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable DEBUG logging.',
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    provider = KrakenDataProvider()

    # ---- Build pair list ------------------------------------------------
    if args.pairs:
        pairs = args.pairs
        logger.info("Using %d explicitly specified pairs.", len(pairs))
    elif args.quote:
        df_pairs = provider.get_pairs_for_quote(args.quote)
        if df_pairs.empty:
            logger.error("No online pairs found for quote currency %r.", args.quote)
            return 1
        pairs = df_pairs['pair'].tolist()
        logger.info(
            "Found %d online pairs quoted in %s.", len(pairs), args.quote.upper()
        )
    else:
        df_pairs = provider.get_tradeable_pairs()
        pairs = df_pairs['pair'].tolist()
        logger.info("Found %d online pairs total.", len(pairs))

    frequencies = args.frequencies
    tasks: List[Tuple[str, str]] = [
        (pair, freq) for freq in frequencies for pair in pairs
    ]

    logger.info(
        "Tasks: %d pairs × %d frequencies = %d downloads  |  output: %s",
        len(pairs), len(frequencies), len(tasks), output_dir,
    )

    # ---- Dry run --------------------------------------------------------
    if args.dry_run:
        existing = sum(
            1 for pair, freq in tasks
            if _parquet_path(output_dir, freq, pair).exists()
        )
        print(f"\nDry run — would process {len(tasks)} tasks "
              f"({existing} existing files would be updated, "
              f"{len(tasks) - existing} new).")
        print(f"Pairs:       {', '.join(pairs[:8])}{'…' if len(pairs) > 8 else ''}")
        print(f"Frequencies: {', '.join(frequencies)}")
        print(f"Output dir:  {output_dir.resolve()}")
        return 0

    # ---- Download -------------------------------------------------------
    rate_limiter = _RateLimiter(calls_per_second=args.rate)
    results: List[_Result] = []

    def _run_task(pair_freq: Tuple[str, str]) -> _Result:
        pair, freq = pair_freq
        return _download_one(provider, pair, freq, output_dir, rate_limiter)

    if tqdm is not None:
        progress = tqdm(total=len(tasks), unit='req', dynamic_ncols=True)
    else:
        progress = None
        logger.info("tqdm not available — progress logged every 100 tasks.")

    _log_every = max(1, len(tasks) // 20)  # log ~20 milestones if no tqdm

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_task, t): t for t in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            desc = f"{result.pair}/{result.frequency} → {result.status}"
            if result.bars_added:
                desc += f" +{result.bars_added}"
            if result.error:
                desc += f" [{result.error[:60]}]"

            if progress is not None:
                progress.set_postfix_str(desc, refresh=False)
                progress.update(1)
            elif i % _log_every == 0 or result.status == 'failed':
                logger.info("[%d/%d] %s", i, len(tasks), desc)

    if progress is not None:
        progress.close()

    # ---- Summary --------------------------------------------------------
    new      = [r for r in results if r.status == 'new']
    updated  = [r for r in results if r.status == 'updated']
    skipped  = [r for r in results if r.status == 'skipped']
    failed   = [r for r in results if r.status == 'failed']
    total_bars = sum(r.bars_added for r in results)

    print("\n" + "=" * 60)
    print("  Kraken bars download — summary")
    print("=" * 60)
    print(f"  New files created : {len(new):>6}")
    print(f"  Files updated     : {len(updated):>6}")
    print(f"  Skipped (up-to-date): {len(skipped):>4}")
    print(f"  Failed            : {len(failed):>6}")
    print(f"  Total bars written: {total_bars:>6,}")
    print(f"  Output directory  : {output_dir.resolve()}")
    print("=" * 60)

    if failed:
        print(f"\n  Failed tasks ({len(failed)}):")
        for r in failed[:20]:
            print(f"    {r.pair}/{r.frequency}: {r.error}")
        if len(failed) > 20:
            print(f"    … and {len(failed) - 20} more")

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
