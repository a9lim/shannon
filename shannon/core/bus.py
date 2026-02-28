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
    TOOL_REQUEST = "tool.request"
    TOOL_RESULT = "tool.result"
    SCHEDULER_TRIGGER = "scheduler.trigger"
    AUTH_CHECK = "auth.check"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MessageIncoming(Event):
    type: EventType = field(default=EventType.MESSAGE_INCOMING, init=False)
    # data keys: platform, channel, user_id, user_name, content, attachments


@dataclass
class MessageOutgoing(Event):
    type: EventType = field(default=EventType.MESSAGE_OUTGOING, init=False)
    # data keys: platform, channel, content, reply_to, embeds, files


@dataclass
class ToolRequest(Event):
    type: EventType = field(default=EventType.TOOL_REQUEST, init=False)
    # data keys: tool_name, arguments, request_id


@dataclass
class ToolResult(Event):
    type: EventType = field(default=EventType.TOOL_RESULT, init=False)
    # data keys: tool_name, request_id, success, output, error


@dataclass
class SchedulerTrigger(Event):
    type: EventType = field(default=EventType.SCHEDULER_TRIGGER, init=False)
    # data keys: job_id, job_name, cron_expr


@dataclass
class AuthCheck(Event):
    type: EventType = field(default=EventType.AUTH_CHECK, init=False)
    # data keys: platform, user_id, required_level


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
                await log.awarning(
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
                await log.aexception("handler_error", event_type=event_type)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
