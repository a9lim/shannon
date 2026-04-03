import asyncio
from shannon.bus import EventBus


async def test_subscribe_and_publish():
    bus = EventBus()
    received = []

    class TestEvent:
        def __init__(self, value: str):
            self.value = value

    async def handler(event: TestEvent):
        received.append(event.value)

    bus.subscribe(TestEvent, handler)
    await bus.publish(TestEvent("hello"))

    assert received == ["hello"]


async def test_multiple_subscribers():
    bus = EventBus()
    received_a = []
    received_b = []

    class TestEvent:
        def __init__(self, value: str):
            self.value = value

    async def handler_a(event: TestEvent):
        received_a.append(event.value)

    async def handler_b(event: TestEvent):
        received_b.append(event.value)

    bus.subscribe(TestEvent, handler_a)
    bus.subscribe(TestEvent, handler_b)
    await bus.publish(TestEvent("world"))

    assert received_a == ["world"]
    assert received_b == ["world"]


async def test_no_subscribers():
    bus = EventBus()

    class TestEvent:
        pass

    # Should not raise
    await bus.publish(TestEvent())


async def test_different_event_types():
    bus = EventBus()
    received = []

    class EventA:
        pass

    class EventB:
        pass

    async def handler_a(event: EventA):
        received.append("a")

    async def handler_b(event: EventB):
        received.append("b")

    bus.subscribe(EventA, handler_a)
    bus.subscribe(EventB, handler_b)

    await bus.publish(EventA())
    assert received == ["a"]

    await bus.publish(EventB())
    assert received == ["a", "b"]


async def test_unsubscribe():
    bus = EventBus()
    received = []

    class TestEvent:
        pass

    async def handler(event: TestEvent):
        received.append(True)

    bus.subscribe(TestEvent, handler)
    await bus.publish(TestEvent())
    assert received == [True]

    bus.unsubscribe(TestEvent, handler)
    await bus.publish(TestEvent())
    assert received == [True]  # No new append


async def test_publish_exception_in_handler_does_not_block_others():
    bus = EventBus()
    ran = []

    class TestEvent:
        pass

    async def bad_handler(event: TestEvent):
        raise RuntimeError("boom")

    async def good_handler(event: TestEvent):
        ran.append(True)

    bus.subscribe(TestEvent, bad_handler)
    bus.subscribe(TestEvent, good_handler)
    await bus.publish(TestEvent())

    assert ran == [True]


async def test_publish_handler_mutation_does_not_skip():
    bus = EventBus()
    ran = []

    class TestEvent:
        pass

    async def self_unsubscribing_handler(event: TestEvent):
        bus.unsubscribe(TestEvent, self_unsubscribing_handler)

    async def second_handler(event: TestEvent):
        ran.append(True)

    bus.subscribe(TestEvent, self_unsubscribing_handler)
    bus.subscribe(TestEvent, second_handler)
    await bus.publish(TestEvent())

    assert ran == [True]
