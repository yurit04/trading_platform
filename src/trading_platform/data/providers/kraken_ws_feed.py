"""
Kraken live market data feed via WebSocket API v2.

Maintains an in-memory order book for each subscribed symbol and fires
registered callbacks on every update.  Optionally writes snapshots to an
OrderBookStorage instance for historical replay.

Usage (standalone async)::

    feed = KrakenWebSocketFeed(
        symbols=["BTC/USD", "ETH/USD"],
        depth=10,
        storage=OrderBookStorage("data/orderbook"),
    )
    feed.on_book_update(lambda sym, book: print(sym, book.best_bid()))
    await feed.run()

Usage (in a thread alongside sync trading engine)::

    def _run(feed):
        asyncio.run(feed.run())

    feed = KrakenWebSocketFeed(["BTC/USD"])
    t = threading.Thread(target=_run, args=(feed,), daemon=True)
    t.start()
    # feed.get_best_bid_ask("BTC/USD") is safe to call from the main thread
"""
import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

_WS_URL = "wss://ws.kraken.com/v2"


class OrderBook:
    """
    In-memory limit order book for one symbol.

    Bids and asks are stored as {price: qty} dicts.
    qty == 0 in an update means the level should be removed.
    All read methods are thread-safe (protected by an RLock).
    """

    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.timestamp: Optional[datetime] = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Mutations (called from the async feed loop)
    # ------------------------------------------------------------------

    def apply_snapshot(
        self,
        bids: List[Dict],
        asks: List[Dict],
        ts: datetime,
    ) -> None:
        with self._lock:
            self.bids = {float(b["price"]): float(b["qty"]) for b in bids}
            self.asks = {float(a["price"]): float(a["qty"]) for a in asks}
            self.timestamp = ts

    def apply_update(
        self,
        bids: List[Dict],
        asks: List[Dict],
        ts: datetime,
    ) -> None:
        with self._lock:
            for b in bids:
                price, qty = float(b["price"]), float(b["qty"])
                if qty == 0.0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = qty
            for a in asks:
                price, qty = float(a["price"]), float(a["qty"])
                if qty == 0.0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = qty
            self.timestamp = ts

    # ------------------------------------------------------------------
    # Read accessors (safe to call from any thread)
    # ------------------------------------------------------------------

    def best_bid(self) -> Optional[Tuple[float, float]]:
        """Return (price, qty) for the best bid, or None."""
        with self._lock:
            if not self.bids:
                return None
            price = max(self.bids)
            return price, self.bids[price]

    def best_ask(self) -> Optional[Tuple[float, float]]:
        """Return (price, qty) for the best ask, or None."""
        with self._lock:
            if not self.asks:
                return None
            price = min(self.asks)
            return price, self.asks[price]

    def mid_price(self) -> Optional[float]:
        """Return mid-price, or None if either side is empty."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid and ask:
            return (bid[0] + ask[0]) / 2
        return None

    def spread(self) -> Optional[float]:
        """Return absolute spread (ask - bid), or None."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid and ask:
            return ask[0] - bid[0]
        return None

    def sorted_bids(self, depth: Optional[int] = None) -> List[Tuple[float, float]]:
        """Return bids sorted best-first (descending price)."""
        with self._lock:
            items = sorted(self.bids.items(), reverse=True)
        return items[:depth] if depth else items

    def sorted_asks(self, depth: Optional[int] = None) -> List[Tuple[float, float]]:
        """Return asks sorted best-first (ascending price)."""
        with self._lock:
            items = sorted(self.asks.items())
        return items[:depth] if depth else items

    def to_dict(self, depth: Optional[int] = None) -> Dict[str, Any]:
        return {
            "bids": self.sorted_bids(depth),
            "asks": self.sorted_asks(depth),
            "timestamp": self.timestamp,
            "mid": self.mid_price(),
            "spread": self.spread(),
        }


class KrakenWebSocketFeed:
    """
    Live market data feed from Kraken WebSocket API v2.

    Subscribes to the book, trade, and ticker channels for the given symbols.
    Maintains an in-memory OrderBook per symbol that is safe to read from any
    thread while the async feed loop runs.

    Callbacks receive data synchronously within the async loop; keep them fast
    or schedule heavy work on a separate executor.

    Args:
        symbols:    Kraken pair names, e.g. ["BTC/USD", "ETH/USD"].
        depth:      Order book depth per side (10 | 25 | 100 | 500 | 1000).
        config:     Optional dict (not currently required for public channels).
        storage:    Optional OrderBookStorage; receives a snapshot after every
                    book update.
        event_bus:  Optional EventBus; publishes a MarketEvent on each ticker
                    update so the trading engine can act on it.
    """

    def __init__(
        self,
        symbols: List[str],
        depth: int = 10,
        config: Optional[Dict[str, Any]] = None,
        storage=None,
        event_bus=None,
    ):
        self.symbols = symbols
        self.depth = depth
        self.config = config or {}
        self.storage = storage
        self.event_bus = event_bus

        self._books: Dict[str, OrderBook] = {s: OrderBook() for s in symbols}
        self._running = False

        self._book_callbacks: List[Callable] = []
        self._trade_callbacks: List[Callable] = []
        self._ticker_callbacks: List[Callable] = []

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_book_update(self, callback: Callable[[str, OrderBook], None]) -> None:
        """Register a callback called with (symbol, OrderBook) on each update."""
        self._book_callbacks.append(callback)

    def on_trade(self, callback: Callable[[str, Dict], None]) -> None:
        """Register a callback called with (symbol, trade_dict) on each trade."""
        self._trade_callbacks.append(callback)

    def on_ticker(self, callback: Callable[[str, Dict], None]) -> None:
        """Register a callback called with (symbol, ticker_dict) on each tick."""
        self._ticker_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Book state accessors (thread-safe)
    # ------------------------------------------------------------------

    def get_book(self, symbol: str) -> Optional[OrderBook]:
        """Return the live OrderBook for a symbol (or None if not subscribed)."""
        return self._books.get(symbol)

    def get_best_bid_ask(
        self, symbol: str
    ) -> Tuple[Optional[float], Optional[float]]:
        """Return (best_bid_price, best_ask_price) or (None, None)."""
        book = self._books.get(symbol)
        if book is None:
            return None, None
        bid = book.best_bid()
        ask = book.best_ask()
        return (bid[0] if bid else None), (ask[0] if ask else None)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Start the feed, reconnecting automatically on disconnection.

        Run this in an asyncio event loop::

            asyncio.run(feed.run())
        """
        self._running = True
        delay = 1
        while self._running:
            try:
                await self._connect_and_process()
                delay = 1
            except Exception as exc:
                if not self._running:
                    break
                logger.warning(
                    "Kraken WS disconnected (%s). Reconnecting in %ds...", exc, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    def stop(self) -> None:
        """Signal the feed to stop after the current message."""
        self._running = False

    # ------------------------------------------------------------------
    # Internal – connection
    # ------------------------------------------------------------------

    async def _connect_and_process(self) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(_WS_URL, heartbeat=30) as ws:
                logger.info("Connected to Kraken WebSocket")
                await self._subscribe(ws)
                async for msg in ws:
                    if not self._running:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._dispatch(json.loads(msg.data))
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        logger.warning("Kraken WS closed: %s", msg.data)
                        break

    async def _subscribe(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        await ws.send_json({
            "method": "subscribe",
            "params": {"channel": "book", "symbol": self.symbols, "depth": self.depth},
        })
        await ws.send_json({
            "method": "subscribe",
            "params": {"channel": "trade", "symbol": self.symbols},
        })
        await ws.send_json({
            "method": "subscribe",
            "params": {"channel": "ticker", "symbol": self.symbols},
        })
        logger.info("Subscribed to book/trade/ticker for %s", self.symbols)

    # ------------------------------------------------------------------
    # Internal – message dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, msg: Dict[str, Any]) -> None:
        channel = msg.get("channel")

        if channel == "heartbeat":
            return

        if channel == "status":
            status = (msg.get("data") or [{}])[0].get("system", "?")
            logger.info("Kraken system status: %s", status)
            return

        if channel is None:
            # Subscription confirmation / error
            if not msg.get("success", True):
                logger.error("Subscription error: %s", msg.get("error"))
            return

        msg_type = msg.get("type", "update")
        data = msg.get("data") or []

        if channel == "book":
            for item in data:
                await self._handle_book(item, msg_type)
        elif channel == "trade":
            for item in data:
                self._fire(self._trade_callbacks, item.get("symbol", ""), item)
        elif channel == "ticker":
            for item in data:
                self._handle_ticker(item)

    async def _handle_book(self, item: Dict, msg_type: str) -> None:
        symbol = item.get("symbol", "")
        bids = item.get("bids") or []
        asks = item.get("asks") or []
        ts = _parse_ts(item.get("timestamp", ""))

        book = self._books.setdefault(symbol, OrderBook())
        if msg_type == "snapshot":
            book.apply_snapshot(bids, asks, ts)
        else:
            book.apply_update(bids, asks, ts)

        if self.storage is not None:
            self.storage.record_snapshot(
                symbol, book.sorted_bids(), book.sorted_asks(), ts
            )

        for cb in self._book_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(symbol, book)
                else:
                    cb(symbol, book)
            except Exception:
                logger.exception("Error in book callback")

    def _handle_ticker(self, item: Dict) -> None:
        symbol = item.get("symbol", "")

        # Publish to EventBus as a MarketEvent so the trading engine sees it
        if self.event_bus is not None:
            self._publish_market_event(symbol, item)

        self._fire(self._ticker_callbacks, symbol, item)

    def _publish_market_event(self, symbol: str, ticker: Dict) -> None:
        try:
            from ...core.event import MarketEvent
            from ...core.enums import AssetClass
            last = float(ticker.get("last", 0) or 0)
            if last == 0:
                return
            event = MarketEvent(
                timestamp=_parse_ts(ticker.get("timestamp", "")),
                symbol=symbol,
                open=float(ticker.get("open", last)),
                high=float(ticker.get("high", last)),
                low=float(ticker.get("low", last)),
                close=last,
                volume=float(ticker.get("volume", 0) or 0),
                asset_class=AssetClass.CRYPTO,
            )
            self.event_bus.publish(event)
        except Exception:
            logger.exception("Failed to publish MarketEvent for %s", symbol)

    @staticmethod
    def _fire(callbacks: List[Callable], symbol: str, payload: Any) -> None:
        for cb in callbacks:
            try:
                cb(symbol, payload)
            except Exception:
                logger.exception("Error in callback %s", cb)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_ts(ts_str: str) -> datetime:
    """Parse Kraken ISO-8601 timestamp to a UTC-aware datetime."""
    if not ts_str:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=timezone.utc)
