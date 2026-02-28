"""Tests for the async event bus."""

import asyncio
import pytest
from shannon.core.bus import EventBus, EventType, Event, MessageIncoming, MessageOutgoing
from shannon.models import IncomingMessage, OutgoingMessage


@pytest.fixture
def bus():
    return EventBus()


class TestEventBus:
    async def test_publish_subscribe(self, bus):
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.MESSAGE_INCOMING, handler)
        await bus.start()

        msg = IncomingMessage(platform="test", channel="ch", user_id="u", content="hello")
        event = MessageIncoming(message=msg)
        await bus.publish(event)

        # Give consumer time to process
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].message.content == "hello"
        assert received[0].type == EventType.MESSAGE_INCOMING

        await bus.stop()

    async def test_multiple_subscribers(self, bus):
        received_a = []
        received_b = []

        async def handler_a(event: Event):
            received_a.append(event)

        async def handler_b(event: Event):
            received_b.append(event)

        bus.subscribe(EventType.MESSAGE_INCOMING, handler_a)
        bus.subscribe(EventType.MESSAGE_INCOMING, handler_b)
        await bus.start()

        msg = IncomingMessage(platform="test", channel="ch", user_id="u", content="test")
        await bus.publish(MessageIncoming(message=msg))
        await asyncio.sleep(0.1)

        assert len(received_a) == 1
        assert len(received_b) == 1

        await bus.stop()

    async def test_event_type_filtering(self, bus):
        incoming = []
        outgoing = []

        async def on_incoming(event: Event):
            incoming.append(event)

        async def on_outgoing(event: Event):
            outgoing.append(event)

        bus.subscribe(EventType.MESSAGE_INCOMING, on_incoming)
        bus.subscribe(EventType.MESSAGE_OUTGOING, on_outgoing)
        await bus.start()

        in_msg = IncomingMessage(platform="test", channel="ch", user_id="u", content="in")
        out_msg = OutgoingMessage(platform="test", channel="ch", content="out")
        await bus.publish(MessageIncoming(message=in_msg))
        await bus.publish(MessageOutgoing(message=out_msg))
        await asyncio.sleep(0.1)

        assert len(incoming) == 1
        assert len(outgoing) == 1
        assert incoming[0].message.content == "in"
        assert outgoing[0].message.content == "out"

        await bus.stop()

    async def test_handler_error_doesnt_crash_bus(self, bus):
        good_received = []

        async def bad_handler(event: Event):
            raise RuntimeError("boom")

        async def good_handler(event: Event):
            good_received.append(event)

        bus.subscribe(EventType.MESSAGE_INCOMING, bad_handler)
        bus.subscribe(EventType.MESSAGE_INCOMING, good_handler)
        await bus.start()

        msg = IncomingMessage(platform="test", channel="ch", user_id="u", content="test")
        await bus.publish(MessageIncoming(message=msg))
        await asyncio.sleep(0.1)

        # Good handler should still receive the event
        assert len(good_received) == 1

        await bus.stop()

    async def test_event_has_id_and_timestamp(self):
        msg = IncomingMessage(platform="test", channel="ch", user_id="u", content="test")
        event = MessageIncoming(message=msg)
        assert event.id  # non-empty
        assert event.timestamp is not None

    async def test_queue_overflow_doesnt_crash(self):
        bus = EventBus(max_queue_size=2)
        received = []

        async def slow_handler(event: Event):
            await asyncio.sleep(1)
            received.append(event)

        bus.subscribe(EventType.MESSAGE_INCOMING, slow_handler)
        await bus.start()

        # Publish more events than queue size
        for i in range(5):
            msg = IncomingMessage(platform="test", channel="ch", user_id="u", content=str(i))
            await bus.publish(MessageIncoming(message=msg))

        await asyncio.sleep(0.1)
        await bus.stop()
        # Should not raise
