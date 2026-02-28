"""Tests for the messaging system: MessagingProvider ABC, DiscordProvider, MessagingManager."""

from __future__ import annotations

import asyncio

import pytest
from typing import Any, Callable, Coroutine

from shannon.bus import EventBus
from shannon.config import MessagingConfig
from shannon.events import ChatMessage, ChatReaction, ChatResponse
from shannon.messaging.providers.base import MessagingProvider
from shannon.messaging.manager import MessagingManager


# ---------------------------------------------------------------------------
# FakeMessaging provider
# ---------------------------------------------------------------------------

class FakeMessagingProvider(MessagingProvider):
    """In-memory messaging provider for tests."""

    def __init__(self, name: str = "fake") -> None:
        self._name = name
        self._callback: Callable[..., Coroutine[Any, Any, None]] | None = None
        self.connected = False
        self.sent_messages: list[tuple[str, str, str | None]] = []
        self.typing_channels: list[str] = []
        self.reactions: list[tuple[str, str, str]] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        self.sent_messages.append((channel, text, reply_to))

    async def send_typing(self, channel: str) -> None:
        self.typing_channels.append(channel)

    async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None:
        self.reactions.append((channel, message_id, emoji))

    def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        self._callback = callback

    def platform_name(self) -> str:
        return self._name

    async def simulate_message(
        self,
        text: str,
        author: str,
        channel_id: str,
        message_id: str,
        attachments: list[dict] | None = None,
        is_reply_to_bot: bool = False,
        is_mention: bool = False,
        custom_emojis: str = "",
        participants: dict[str, str] | None = None,
        is_in_conversation: bool = False,
    ) -> None:
        """Simulate an incoming message from this platform."""
        if self._callback is not None:
            await self._callback(
                text, author, channel_id, message_id,
                attachments or [], is_reply_to_bot, is_mention,
                custom_emojis, participants or {},
                is_in_conversation,
            )


# ---------------------------------------------------------------------------
# MessagingProvider ABC guards
# ---------------------------------------------------------------------------

def test_messaging_provider_is_abstract():
    """MessagingProvider cannot be instantiated directly."""
    try:
        MessagingProvider()
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


def test_messaging_provider_missing_connect():
    """A subclass missing connect() cannot be instantiated."""

    class Incomplete(MessagingProvider):
        async def disconnect(self) -> None: ...
        async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None: ...
        async def send_typing(self, channel: str) -> None: ...
        async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None: ...
        def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None: ...
        def platform_name(self) -> str: return "x"

    try:
        Incomplete()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_messaging_provider_concrete_subclass_instantiates():
    """A fully implemented MessagingProvider subclass can be instantiated."""
    provider = FakeMessagingProvider()
    assert isinstance(provider, MessagingProvider)


# ---------------------------------------------------------------------------
# MessagingProvider ABC guards — new methods
# ---------------------------------------------------------------------------

class TestMessagingProviderNewMethods:
    def test_provider_requires_send_typing(self):
        """A subclass missing send_typing() cannot be instantiated."""
        class Incomplete(MessagingProvider):
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def send_message(self, channel, text, reply_to=None) -> None: ...
            def on_message(self, callback) -> None: ...
            def platform_name(self) -> str: return "x"
            async def add_reaction(self, channel, message_id, emoji) -> None: ...

        try:
            Incomplete()
            assert False, "Should not instantiate with missing send_typing"
        except TypeError:
            pass

    def test_provider_requires_add_reaction(self):
        """A subclass missing add_reaction() cannot be instantiated."""
        class Incomplete(MessagingProvider):
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def send_message(self, channel, text, reply_to=None) -> None: ...
            def on_message(self, callback) -> None: ...
            def platform_name(self) -> str: return "x"
            async def send_typing(self, channel) -> None: ...

        try:
            Incomplete()
            assert False, "Should not instantiate with missing add_reaction"
        except TypeError:
            pass


# ---------------------------------------------------------------------------
# MessagingManager — receives message → emits ChatMessage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_incoming_message_emits_chat_message():
    """When a provider receives a message, MessagingManager emits a ChatMessage event."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    received: list[ChatMessage] = []

    async def capture(event: ChatMessage) -> None:
        received.append(event)

    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message(
        text="hello bot",
        author="user123",
        channel_id="chan-1",
        message_id="msg-1",
        is_mention=True,
    )
    await asyncio.sleep(0.05)

    assert len(received) == 1
    msg = received[0]
    assert msg.text == "hello bot"
    assert msg.author == "user123"
    assert msg.platform == "discord"
    assert msg.channel == "chan-1"
    assert msg.message_id == "msg-1"


@pytest.mark.asyncio
async def test_manager_incoming_message_has_correct_platform():
    """ChatMessage platform field matches the provider's platform_name."""
    bus = EventBus()
    provider = FakeMessagingProvider("twitch")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    received: list[ChatMessage] = []

    async def capture(event: ChatMessage) -> None:
        received.append(event)

    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("hi", "someone", "chan", "msg-99", is_mention=True)
    await asyncio.sleep(0.05)

    assert received[0].platform == "twitch"


# ---------------------------------------------------------------------------
# MessagingManager — ChatResponse → provider send_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_chat_response_routes_to_correct_provider():
    """Publishing a ChatResponse routes to the matching provider's send_message."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    await bus.publish(ChatResponse(
        text="Hello back!",
        platform="discord",
        channel="chan-1",
        reply_to="msg-1",
    ))

    assert len(provider.sent_messages) == 1
    channel, text, reply_to = provider.sent_messages[0]
    assert channel == "chan-1"
    assert text == "Hello back!"
    assert reply_to == "msg-1"


@pytest.mark.asyncio
async def test_manager_chat_response_without_reply_to():
    """ChatResponse with empty reply_to passes None to send_message."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    await bus.publish(ChatResponse(
        text="Just a message",
        platform="discord",
        channel="general",
        reply_to="",
    ))

    assert len(provider.sent_messages) == 1
    _, _, reply_to = provider.sent_messages[0]
    assert reply_to is None


# ---------------------------------------------------------------------------
# MessagingManager — multiple platforms routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_multiple_platforms_routes_to_correct_one():
    """With multiple providers, ChatResponse goes only to the matching platform."""
    bus = EventBus()
    discord = FakeMessagingProvider("discord")
    twitch = FakeMessagingProvider("twitch")
    manager = MessagingManager(bus, [discord, twitch], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    await bus.publish(ChatResponse(text="hey twitch", platform="twitch", channel="stream", reply_to=""))

    assert len(discord.sent_messages) == 0
    assert len(twitch.sent_messages) == 1
    assert twitch.sent_messages[0][1] == "hey twitch"


@pytest.mark.asyncio
async def test_manager_multiple_platforms_each_emits_chat_message():
    """Messages from different providers are both published as ChatMessage events."""
    bus = EventBus()
    discord = FakeMessagingProvider("discord")
    twitch = FakeMessagingProvider("twitch")
    manager = MessagingManager(bus, [discord, twitch], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    received: list[ChatMessage] = []

    async def capture(event: ChatMessage) -> None:
        received.append(event)

    bus.subscribe(ChatMessage, capture)

    await discord.simulate_message("hello discord", "user_a", "dc-chan", "dc-msg", is_mention=True)
    await twitch.simulate_message("hello twitch", "user_b", "tw-chan", "tw-msg", is_mention=True)
    await asyncio.sleep(0.05)

    assert len(received) == 2
    platforms = {m.platform for m in received}
    assert platforms == {"discord", "twitch"}


@pytest.mark.asyncio
async def test_manager_unknown_platform_response_is_ignored():
    """ChatResponse for an unknown platform does not raise and is silently dropped."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    # Should not raise
    await bus.publish(ChatResponse(text="orphan", platform="unknown", channel="x", reply_to=""))

    assert len(provider.sent_messages) == 0


# ---------------------------------------------------------------------------
# MessagingManager — connect/disconnect lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_start_connects_all_providers():
    """start() calls connect() on all providers."""
    bus = EventBus()
    p1 = FakeMessagingProvider("a")
    p2 = FakeMessagingProvider("b")
    manager = MessagingManager(bus, [p1, p2], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    assert p1.connected
    assert p2.connected


@pytest.mark.asyncio
async def test_manager_stop_disconnects_all_providers():
    """stop() calls disconnect() on all providers."""
    bus = EventBus()
    p1 = FakeMessagingProvider("a")
    p2 = FakeMessagingProvider("b")
    manager = MessagingManager(bus, [p1, p2], MessagingConfig(debounce_delay=0.0))
    await manager.start()
    await manager.stop()

    assert not p1.connected
    assert not p2.connected


# ---------------------------------------------------------------------------
# MessagingManager — behavioral logic: debounce, should_respond, reactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_debounce_delays_publish():
    """Messages should be delayed by debounce_delay before being published."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.1)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("hello", "user", "chan", "msg1", is_mention=True)
    assert len(received) == 0
    await asyncio.sleep(0.2)
    assert len(received) == 1
    assert received[0].text == "hello"


@pytest.mark.asyncio
async def test_manager_debounce_cancels_previous():
    """A second message in the same channel should cancel the first debounce."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.2)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("first", "user", "chan", "msg1", is_mention=True)
    await asyncio.sleep(0.05)
    await provider.simulate_message("second", "user", "chan", "msg2", is_mention=True)
    await asyncio.sleep(0.3)
    assert len(received) == 1
    assert received[0].text == "second"


@pytest.mark.asyncio
async def test_manager_responds_to_mention():
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("hey bot", "user", "chan", "msg1", is_mention=True)
    await asyncio.sleep(0.05)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_manager_responds_to_reply():
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("reply", "user", "chan", "msg1", is_reply_to_bot=True)
    await asyncio.sleep(0.05)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_manager_ignores_unrelated_message():
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, reply_probability=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("random", "user", "chan", "msg1")
    await asyncio.sleep(0.05)
    assert len(received) == 0


@pytest.mark.asyncio
async def test_manager_conversation_continuity():
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, conversation_expiry=10.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("follow up", "user", "chan", "msg2", is_in_conversation=True)
    await asyncio.sleep(0.05)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_manager_conversation_expired():
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, conversation_expiry=0.01)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message("too late", "user", "chan", "msg2", is_in_conversation=False)
    await asyncio.sleep(0.05)
    assert len(received) == 0



@pytest.mark.asyncio
async def test_manager_routes_reactions():
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    await bus.publish(ChatResponse(
        text="nice", platform="discord", channel="chan",
        reply_to="msg1", reactions=["👍", "🎉"],
    ))

    assert len(provider.reactions) == 2
    assert provider.reactions[0] == ("chan", "msg1", "👍")
    assert provider.reactions[1] == ("chan", "msg1", "🎉")


@pytest.mark.asyncio
async def test_full_flow_mention_debounce_react():
    """End-to-end: mention -> debounce -> publish -> response with reactions -> provider."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.05)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    # Subscribe to ChatMessage and auto-respond with reactions
    async def auto_respond(event: ChatMessage):
        await bus.publish(ChatResponse(
            text="Got it!",
            platform=event.platform,
            channel=event.channel,
            reply_to=event.message_id,
            reactions=["👍"],
        ))

    bus.subscribe(ChatMessage, auto_respond)

    # Simulate an @mention
    await provider.simulate_message(
        "hello bot", "user", "chan1", "msg1", is_mention=True,
    )

    # Wait for debounce + processing
    await asyncio.sleep(0.15)

    # Verify message was sent
    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0][1] == "Got it!"

    # Verify reaction was applied
    assert len(provider.reactions) == 1
    assert provider.reactions[0] == ("chan1", "msg1", "👍")

    await manager.stop()


@pytest.mark.asyncio
async def test_manager_passes_custom_emojis():
    """custom_emojis from provider callback should appear in ChatMessage event."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message(
        "hi", "user", "chan", "msg1",
        is_mention=True, custom_emojis=":pepe:, :sadge:",
    )
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].custom_emojis == ":pepe:, :sadge:"


@pytest.mark.asyncio
async def test_manager_passes_participants():
    """participants from provider callback should appear in ChatMessage event."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    manager = MessagingManager(bus, [provider], MessagingConfig(debounce_delay=0.0))
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message(
        "hi", "user", "chan", "msg1",
        is_mention=True, participants={"123": "Alice"},
    )
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].participants == {"123": "Alice"}


@pytest.mark.asyncio
async def test_manager_responds_when_in_conversation():
    """Messages should get responses when is_in_conversation is True."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, reply_probability=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message(
        "follow up", "user", "chan", "msg1", is_in_conversation=True,
    )
    await asyncio.sleep(0.05)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_manager_sends_typing_on_chat_response():
    """MessagingManager should send typing indicator when receiving ChatResponse."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    await bus.publish(ChatResponse(
        text="Hello!", platform="discord", channel="chan1", reply_to="msg1",
    ))

    assert "chan1" in provider.typing_channels


@pytest.mark.asyncio
async def test_manager_ignores_when_not_in_conversation():
    """Messages should be ignored when not mentioned, not in conversation, and no random chance."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, reply_probability=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    await provider.simulate_message(
        "random msg", "user", "chan", "msg1", is_in_conversation=False,
    )
    await asyncio.sleep(0.05)
    assert len(received) == 0
