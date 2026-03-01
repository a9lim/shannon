"""Async pub/sub event bus."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine
from uuid import uuid4

from shannon.utils.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    MESSAGE_INCOMING = "message.incoming"
    MESSAGE_OUTGOING = "message.outgoing"
    SCHEDULER_TRIGGER = "scheduler.trigger"
    WEBHOOK_RECEIVED = "webhook.received"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MessageIncoming(Event):
    type: EventType = field(default=EventType.MESSAGE_INCOMING, init=False)

    # Typed payload — populated by transports, consumed by pipeline
    message: "IncomingMessage | None" = field(default=None)


@dataclass
class MessageOutgoing(Event):
    type: EventType = field(default=EventType.MESSAGE_OUTGOING, init=False)

    # Typed payload — populated by pipeline, consumed by transports
    message: "OutgoingMessage | None" = field(default=None)


@dataclass
class SchedulerTrigger(Event):
    type: EventType = field(default=EventType.SCHEDULER_TRIGGER, init=False)
    # data keys: job_id, job_name, cron_expr


@dataclass
class WebhookReceived(Event):
    type: EventType = field(default=EventType.WEBHOOK_RECEIVED, init=False)
    # data keys: source, event_type, summary, payload, channel_target


# Deferred import to avoid circular dependency at module level
from shannon.models import IncomingMessage, OutgoingMessage  # noqa: E402


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------

Handler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self, max_queue_size: int = 256) -> None:
        self._subscribers: dict[EventType, list[tuple[Handler, asyncio.Queue[Event]]]] = {}
        self._max_queue_size = max_queue_size
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers.setdefault(event_type, []).append((handler, queue))

    async def publish(self, event: Event) -> None:
        handlers = self._subscribers.get(event.type, [])
        for handler, queue in handlers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning(
                    "event_queue_full",
                    event_type=event.type.value,
                    handler=handler.__qualname__,
                )

    async def start(self) -> None:
        self._running = True
        for event_type, handler_list in self._subscribers.items():
            for handler, queue in handler_list:
                task = asyncio.create_task(
                    self._consumer(handler, queue, event_type.value),
                    name=f"bus-{event_type.value}-{handler.__qualname__}",
                )
                self._tasks.append(task)

    async def _consumer(
        self, handler: Handler, queue: asyncio.Queue[Event], event_type: str
    ) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await handler(event)
            except Exception:
                log.exception("handler_error", event_type=event_type)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
