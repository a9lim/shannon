"""Typed async event bus — publish/subscribe pattern."""

import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class EventBus:
    """Central event bus. Modules subscribe to event types and publish events."""

    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable[..., Coroutine[Any, Any, None]]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Register a handler for an event type."""
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Remove a handler for an event type."""
        try:
            self._subscribers[event_type].remove(handler)
        except ValueError:
            pass

    async def publish(self, event: Any) -> None:
        """Publish an event to all subscribers of its type."""
        for handler in list(self._subscribers.get(type(event), [])):
            try:
                await handler(event)
            except Exception:
                logger.exception("Unhandled exception in event handler %r for event %r", handler, event)
