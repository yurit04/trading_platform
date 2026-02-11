"""
Event bus for event-driven architecture.
Manages event distribution to subscribers.
"""
from typing import Dict, List, Callable, Type, Optional
from collections import defaultdict
from datetime import datetime
import asyncio
import logging
from queue import PriorityQueue, Empty

from .event import Event, EventType
from .exceptions import EventException


logger = logging.getLogger(__name__)


class EventBus:
    """
    Central event bus for distributing events to subscribers.
    
    Supports both synchronous (backtest) and asynchronous (live) modes.
    """
    
    def __init__(self, mode: str = 'sync'):
        """
        Initialize event bus.
        
        Args:
            mode: 'sync' for backtest, 'async' for live trading
        """
        self.mode = mode
        self._subscribers: Dict[Type[Event], List[Callable]] = defaultdict(list)
        self._event_log: List[Event] = []
        self._log_events = True
        
        # For backtest mode - priority queue ordered by timestamp
        self._event_queue: Optional[PriorityQueue] = None
        if mode == 'sync':
            self._event_queue = PriorityQueue()
        
        logger.info(f"EventBus initialized in {mode} mode")
    
    def subscribe(self, event_type: Type[Event], callback: Callable[[Event], None]) -> None:
        """
        Subscribe to events of a specific type.
        
        Args:
            event_type: Type of event to subscribe to
            callback: Function to call when event is published
        """
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)
            logger.debug(f"Subscribed {callback.__name__} to {event_type.__name__}")
    
    def unsubscribe(self, event_type: Type[Event], callback: Callable[[Event], None]) -> None:
        """
        Unsubscribe from events.
        
        Args:
            event_type: Type of event to unsubscribe from
            callback: Function to remove from subscribers
        """
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Unsubscribed {callback.__name__} from {event_type.__name__}")
    
    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.
        
        Args:
            event: Event to publish
        """
        if self.mode == 'sync':
            self._publish_sync(event)
        else:
            asyncio.create_task(self._publish_async(event))
    
    def _publish_sync(self, event: Event) -> None:
        """Synchronously publish event (backtest mode)."""
        if self._log_events:
            self._event_log.append(event)
        
        # Get subscribers for this specific event type
        event_class = type(event)
        subscribers = self._subscribers.get(event_class, [])
        
        # Also notify subscribers of base Event type (wildcard)
        subscribers.extend(self._subscribers.get(Event, []))
        
        # Call all subscribers
        for callback in subscribers:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in event handler {callback.__name__}: {e}", exc_info=True)
                raise EventException(f"Event handler failed: {callback.__name__}") from e
    
    async def _publish_async(self, event: Event) -> None:
        """Asynchronously publish event (live mode)."""
        if self._log_events:
            self._event_log.append(event)
        
        event_class = type(event)
        subscribers = self._subscribers.get(event_class, [])
        subscribers.extend(self._subscribers.get(Event, []))
        
        # Create tasks for all async subscribers
        tasks = []
        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    tasks.append(asyncio.create_task(callback(event)))
                else:
                    # Run sync callbacks in executor
                    loop = asyncio.get_event_loop()
                    tasks.append(loop.run_in_executor(None, callback, event))
            except Exception as e:
                logger.error(f"Error creating task for {callback.__name__}: {e}", exc_info=True)
        
        # Wait for all handlers to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def put(self, event: Event) -> None:
        """
        Put event in queue (backtest mode only).
        
        Args:
            event: Event to queue
        """
        if self.mode != 'sync' or self._event_queue is None:
            raise EventException("put() only available in sync mode")
        
        # Priority queue uses (priority, item) tuples
        # Use timestamp as priority (earlier events processed first)
        priority = event.timestamp.timestamp()
        self._event_queue.put((priority, event))
    
    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[Event]:
        """
        Get next event from queue (backtest mode only).
        
        Args:
            block: Whether to block waiting for event
            timeout: Timeout in seconds
            
        Returns:
            Next event or None if queue is empty
        """
        if self.mode != 'sync' or self._event_queue is None:
            raise EventException("get() only available in sync mode")
        
        try:
            _, event = self._event_queue.get(block=block, timeout=timeout)
            return event
        except Empty:
            return None
    
    def has_events(self) -> bool:
        """Check if event queue has events (backtest mode only)."""
        if self.mode != 'sync' or self._event_queue is None:
            raise EventException("has_events() only available in sync mode")
        return not self._event_queue.empty()
    
    def clear_queue(self) -> None:
        """Clear all events from queue (backtest mode only)."""
        if self.mode != 'sync' or self._event_queue is None:
            raise EventException("clear_queue() only available in sync mode")
        
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except Empty:
                break
    
    def get_event_log(self) -> List[Event]:
        """Get all logged events."""
        return self._event_log.copy()
    
    def clear_event_log(self) -> None:
        """Clear event log."""
        self._event_log.clear()
    
    def set_logging(self, enabled: bool) -> None:
        """Enable or disable event logging."""
        self._log_events = enabled
    
    def get_event_count(self, event_type: Optional[Type[Event]] = None) -> int:
        """
        Get count of events in log.
        
        Args:
            event_type: Optional event type to filter by
            
        Returns:
            Count of events
        """
        if event_type is None:
            return len(self._event_log)
        return sum(1 for e in self._event_log if isinstance(e, event_type))
    
    def get_subscriber_count(self, event_type: Optional[Type[Event]] = None) -> int:
        """
        Get count of subscribers.
        
        Args:
            event_type: Optional event type to filter by
            
        Returns:
            Count of subscribers
        """
        if event_type is None:
            return sum(len(subs) for subs in self._subscribers.values())
        return len(self._subscribers.get(event_type, []))
    
    def __repr__(self) -> str:
        return (
            f"EventBus(mode={self.mode}, "
            f"subscribers={self.get_subscriber_count()}, "
            f"events_logged={len(self._event_log)})"
        )
