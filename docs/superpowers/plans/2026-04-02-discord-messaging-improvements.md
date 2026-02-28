# Discord & Messaging Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 16 cross-audit improvements from Faithful covering Discord messaging, behavioral chat logic, reaction support, attachment handling, config validation, and Anthropic API hardening.

**Architecture:** Enrich `MessagingManager` with platform-agnostic behavioral logic (debouncing, conversation continuity, random replies/reactions). Enrich `DiscordProvider` with Discord API mechanics (message splitting, typing, reactions, attachments). Add reaction extraction to the brain. Harden the Anthropic API client with message normalization and tool rate limits.

**Tech Stack:** Python 3.12, discord.py, anthropic SDK, pytest + pytest-asyncio

---

### Task 1: Config — Add MessagingConfig Fields and Validation

**Files:**
- Modify: `shannon/config.py:50-53`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for new MessagingConfig defaults**

Add to `tests/test_config.py`:

```python
class TestMessagingConfigDefaults:
    def test_debounce_delay_default(self):
        cfg = MessagingConfig()
        assert cfg.debounce_delay == 3.0

    def test_reply_probability_default(self):
        cfg = MessagingConfig()
        assert cfg.reply_probability == 0.0

    def test_reaction_probability_default(self):
        cfg = MessagingConfig()
        assert cfg.reaction_probability == 0.0

    def test_conversation_expiry_default(self):
        cfg = MessagingConfig()
        assert cfg.conversation_expiry == 300.0

    def test_max_context_messages_default(self):
        cfg = MessagingConfig()
        assert cfg.max_context_messages == 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py::TestMessagingConfigDefaults -v`
Expected: FAIL with AttributeError on missing fields

- [ ] **Step 3: Add new fields to MessagingConfig**

In `shannon/config.py`, replace the `MessagingConfig` dataclass:

```python
@dataclass
class MessagingConfig:
    type: str = "discord"
    enabled: bool = False
    token: str = ""
    debounce_delay: float = 3.0
    reply_probability: float = 0.0
    reaction_probability: float = 0.0
    conversation_expiry: float = 300.0
    max_context_messages: int = 20
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py::TestMessagingConfigDefaults -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for config validation**

Add to `tests/test_config.py`:

```python
import logging

class TestConfigValidation:
    def test_messaging_debounce_delay_clamped_high(self):
        cfg = MessagingConfig(debounce_delay=100.0)
        assert cfg.debounce_delay == 3.0

    def test_messaging_debounce_delay_clamped_low(self):
        cfg = MessagingConfig(debounce_delay=-1.0)
        assert cfg.debounce_delay == 3.0

    def test_messaging_debounce_delay_valid_unchanged(self):
        cfg = MessagingConfig(debounce_delay=5.0)
        assert cfg.debounce_delay == 5.0

    def test_messaging_reply_probability_clamped_high(self):
        cfg = MessagingConfig(reply_probability=2.0)
        assert cfg.reply_probability == 0.0

    def test_messaging_reply_probability_valid_unchanged(self):
        cfg = MessagingConfig(reply_probability=0.5)
        assert cfg.reply_probability == 0.5

    def test_messaging_reaction_probability_clamped_high(self):
        cfg = MessagingConfig(reaction_probability=1.5)
        assert cfg.reaction_probability == 0.0

    def test_messaging_conversation_expiry_clamped_high(self):
        cfg = MessagingConfig(conversation_expiry=5000.0)
        assert cfg.conversation_expiry == 300.0

    def test_messaging_max_context_messages_clamped_negative(self):
        cfg = MessagingConfig(max_context_messages=-1)
        assert cfg.max_context_messages == 0

    def test_llm_max_tokens_clamped_to_minimum(self):
        cfg = LLMConfig(max_tokens=0)
        assert cfg.max_tokens == 1

    def test_llm_max_tokens_valid_unchanged(self):
        cfg = LLMConfig(max_tokens=8000)
        assert cfg.max_tokens == 8000

    def test_config_validation_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            MessagingConfig(debounce_delay=100.0)
        assert "debounce_delay" in caplog.text
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py::TestConfigValidation -v`
Expected: FAIL — no validation yet

- [ ] **Step 7: Implement _clamp helper and __post_init__ validation**

In `shannon/config.py`, add the `_clamp` helper before the dataclass definitions and add `__post_init__` methods:

```python
import logging
import os

_log = logging.getLogger(__name__)


def _clamp(value: float, lo: float, hi: float, name: str, default: float) -> float:
    """Clamp a value to [lo, hi], logging a warning and returning default if out of range."""
    if lo <= value <= hi:
        return value
    _log.warning("%s=%.4g out of range [%.4g, %.4g]; using %.4g.", name, value, lo, hi, default)
    return default
```

Add `__post_init__` to `LLMConfig`:

```python
@dataclass
class LLMConfig:
    model: str = "claude-opus-4-6"
    max_tokens: int = 16000
    thinking: bool = True
    compaction: bool = True
    api_key: str = ""

    def __post_init__(self) -> None:
        self.max_tokens = max(1, self.max_tokens)
        if not self.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            _log.warning("No API key set in config or ANTHROPIC_API_KEY env var.")
```

Add `__post_init__` to `MessagingConfig`:

```python
@dataclass
class MessagingConfig:
    type: str = "discord"
    enabled: bool = False
    token: str = ""
    debounce_delay: float = 3.0
    reply_probability: float = 0.0
    reaction_probability: float = 0.0
    conversation_expiry: float = 300.0
    max_context_messages: int = 20

    def __post_init__(self) -> None:
        self.debounce_delay = _clamp(self.debounce_delay, 0, 60, "debounce_delay", 3.0)
        self.reply_probability = _clamp(self.reply_probability, 0, 1, "reply_probability", 0.0)
        self.reaction_probability = _clamp(self.reaction_probability, 0, 1, "reaction_probability", 0.0)
        self.conversation_expiry = _clamp(self.conversation_expiry, 0, 3600, "conversation_expiry", 300.0)
        self.max_context_messages = max(0, self.max_context_messages)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add shannon/config.py tests/test_config.py
git commit -m "feat: add messaging config fields and config validation"
```

---

### Task 2: Events — Extend ChatMessage, ChatResponse, Add ChatReaction

**Files:**
- Modify: `shannon/events.py`
- Modify: `tests/test_events.py`

- [ ] **Step 1: Write failing tests for new event fields**

Add to `tests/test_events.py`:

```python
from shannon.events import ChatMessage, ChatResponse, ChatReaction


class TestChatMessageExtended:
    def test_attachments_default_empty(self):
        msg = ChatMessage(text="hi", author="u", platform="discord", channel="c")
        assert msg.attachments == []

    def test_is_reply_to_bot_default_false(self):
        msg = ChatMessage(text="hi", author="u", platform="discord", channel="c")
        assert msg.is_reply_to_bot is False

    def test_is_mention_default_false(self):
        msg = ChatMessage(text="hi", author="u", platform="discord", channel="c")
        assert msg.is_mention is False

    def test_attachments_populated(self):
        att = {"filename": "img.png", "content_type": "image/png", "data": b"\x89PNG"}
        msg = ChatMessage(text="look", author="u", platform="d", channel="c", attachments=[att])
        assert len(msg.attachments) == 1
        assert msg.attachments[0]["filename"] == "img.png"


class TestChatResponseExtended:
    def test_reactions_default_empty(self):
        resp = ChatResponse(text="hi", platform="d", channel="c")
        assert resp.reactions == []

    def test_reactions_populated(self):
        resp = ChatResponse(text="hi", platform="d", channel="c", reactions=["👍", "🎉"])
        assert resp.reactions == ["👍", "🎉"]


class TestChatReaction:
    def test_chat_reaction_fields(self):
        r = ChatReaction(emoji="👍", platform="discord", channel="c", message_id="m1")
        assert r.emoji == "👍"
        assert r.platform == "discord"
        assert r.channel == "c"
        assert r.message_id == "m1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_events.py::TestChatMessageExtended tests/test_events.py::TestChatResponseExtended tests/test_events.py::TestChatReaction -v`
Expected: FAIL — missing fields and ChatReaction class

- [ ] **Step 3: Update event dataclasses**

In `shannon/events.py`, update `ChatMessage`:

```python
@dataclass
class ChatMessage:
    """Incoming message from an external chat platform."""
    text: str
    author: str
    platform: str
    channel: str
    message_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    is_reply_to_bot: bool = False
    is_mention: bool = False
```

Update `ChatResponse`:

```python
@dataclass
class ChatResponse:
    """Outgoing response to an external chat platform."""
    text: str
    platform: str
    channel: str
    reply_to: str = ""
    reactions: list[str] = field(default_factory=list)
```

Add `ChatReaction` after `ChatResponse`:

```python
@dataclass
class ChatReaction:
    """Request to add an emoji reaction to a message."""
    emoji: str
    platform: str
    channel: str
    message_id: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_events.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS — new fields have defaults so existing code is unaffected

- [ ] **Step 6: Commit**

```bash
git add shannon/events.py tests/test_events.py
git commit -m "feat: extend ChatMessage/ChatResponse with attachments, reactions, mention flags"
```

---

### Task 3: Reaction Extraction Utility

**Files:**
- Create: `shannon/brain/reactions.py`
- Create: `tests/test_reactions.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reactions.py`:

```python
"""Tests for reaction extraction from LLM output."""

from shannon.brain.reactions import extract_reactions


class TestExtractReactions:
    def test_no_reactions(self):
        clean, reactions = extract_reactions("Hello world")
        assert clean == "Hello world"
        assert reactions == []

    def test_single_reaction(self):
        clean, reactions = extract_reactions("Great message [react: 👍]")
        assert clean == "Great message"
        assert reactions == ["👍"]

    def test_multiple_reactions(self):
        clean, reactions = extract_reactions("Nice [react: 👍] [react: 🎉]")
        assert clean == "Nice"
        assert reactions == ["👍", "🎉"]

    def test_reaction_with_spaces(self):
        clean, reactions = extract_reactions("Ok [react:  😊  ]")
        assert clean == "Ok"
        assert reactions == ["😊"]

    def test_empty_reaction_ignored(self):
        clean, reactions = extract_reactions("Test [react: ]")
        assert clean == "Test"
        assert reactions == []

    def test_reaction_only_message(self):
        clean, reactions = extract_reactions("[react: 👍]")
        assert clean == ""
        assert reactions == ["👍"]

    def test_empty_input(self):
        clean, reactions = extract_reactions("")
        assert clean == ""
        assert reactions == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_reactions.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement extract_reactions**

Create `shannon/brain/reactions.py`:

```python
"""Reaction extraction from LLM response text."""

import re

_REACTION_PATTERN = re.compile(r"\[react:\s*([^\]]+)\]")


def extract_reactions(text: str) -> tuple[str, list[str]]:
    """Strip [react: emoji] markers from text and return (clean_text, reactions)."""
    reactions = _REACTION_PATTERN.findall(text)
    clean = _REACTION_PATTERN.sub("", text).strip()
    return clean, [r.strip() for r in reactions if r.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_reactions.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/brain/reactions.py tests/test_reactions.py
git commit -m "feat: add reaction extraction utility for LLM output"
```

---

### Task 4: Brain — Attachment Handling and Reaction Extraction in Chat Flow

**Files:**
- Modify: `shannon/brain/brain.py:87-98`
- Modify: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests for attachment handling**

Add to `tests/test_brain.py`:

```python
@pytest.mark.asyncio
async def test_brain_chat_message_passes_image_attachments():
    """Image attachments in ChatMessage should be passed as images to the LLM."""
    fake_claude = FakeClaude(text="I see an image!")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    msg = ChatMessage(
        text="What's this?",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
        attachments=[{"filename": "photo.png", "content_type": "image/png", "data": b"\x89PNG"}],
    )
    await bus.publish(msg)

    # Verify the LLM was called (we can't easily inspect images passed, but we verify no crash)
    assert fake_claude.call_count >= 1


@pytest.mark.asyncio
async def test_brain_chat_message_appends_text_attachments():
    """Text file attachments should be appended to the message text."""
    fake_claude = FakeClaude(text="Got it!")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    msg = ChatMessage(
        text="Check this file",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
        attachments=[{"filename": "notes.txt", "content_type": "text/plain", "data": b"hello world"}],
    )
    await bus.publish(msg)

    assert fake_claude.call_count >= 1
```

- [ ] **Step 2: Write failing tests for reaction extraction**

Add to `tests/test_brain.py`:

```python
@pytest.mark.asyncio
async def test_brain_chat_response_extracts_reactions():
    """Reactions in LLM output should be extracted into ChatResponse.reactions."""
    fake_claude = FakeClaude(text="Great message! [react: 👍]")
    bus, brain = _make_brain(fake_claude=fake_claude)

    chat_responses: list[ChatResponse] = []

    async def capture_chat(event: ChatResponse):
        chat_responses.append(event)

    bus.subscribe(ChatResponse, capture_chat)
    await brain.start()

    msg = ChatMessage(
        text="Hello!",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
    )
    await bus.publish(msg)

    assert len(chat_responses) == 1
    assert chat_responses[0].text == "Great message!"
    assert chat_responses[0].reactions == ["👍"]


@pytest.mark.asyncio
async def test_brain_chat_response_no_reactions():
    """ChatResponse.reactions should be empty when LLM output has no reaction markers."""
    fake_claude = FakeClaude(text="Just a normal reply")
    bus, brain = _make_brain(fake_claude=fake_claude)

    chat_responses: list[ChatResponse] = []

    async def capture_chat(event: ChatResponse):
        chat_responses.append(event)

    bus.subscribe(ChatResponse, capture_chat)
    await brain.start()

    msg = ChatMessage(
        text="Hello!",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
    )
    await bus.publish(msg)

    assert len(chat_responses) == 1
    assert chat_responses[0].text == "Just a normal reply"
    assert chat_responses[0].reactions == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_brain.py::test_brain_chat_message_passes_image_attachments tests/test_brain.py::test_brain_chat_message_appends_text_attachments tests/test_brain.py::test_brain_chat_response_extracts_reactions tests/test_brain.py::test_brain_chat_response_no_reactions -v`
Expected: FAIL

- [ ] **Step 4: Implement attachment handling and reaction extraction in brain**

In `shannon/brain/brain.py`, add the import at the top:

```python
from shannon.brain.reactions import extract_reactions
```

Replace the `_on_chat_message` method (lines 87-98):

```python
    async def _on_chat_message(self, event: ChatMessage) -> None:
        logger.debug("Received ChatMessage from %s/%s: %r", event.platform, event.channel, event.text)

        # Extract images and text from attachments
        images: list[bytes] = []
        text = event.text
        for att in event.attachments:
            ct = att.get("content_type", "")
            if ct.startswith("image/"):
                images.append(att["data"])
            elif ct.startswith("text/"):
                file_text = att["data"].decode("utf-8", errors="replace")
                text += f"\n[File: {att['filename']}]\n{file_text}"
            else:
                text += f"\n[Attached file: {att['filename']}]"

        responses = await self._process_input(text=text, images=images)
        for i, response_text in enumerate(responses):
            clean_text, reactions = extract_reactions(response_text)
            if clean_text or reactions:
                await self._bus.publish(
                    ChatResponse(
                        text=clean_text,
                        platform=event.platform,
                        channel=event.channel,
                        reply_to=event.message_id if i == 0 else "",
                        reactions=reactions,
                    )
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_brain.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add shannon/brain/brain.py tests/test_brain.py
git commit -m "feat: add attachment handling and reaction extraction to brain chat flow"
```

---

### Task 5: MessagingProvider Base — Extend Interface

**Files:**
- Modify: `shannon/messaging/providers/base.py`
- Modify: `tests/test_messaging.py`

- [ ] **Step 1: Write failing tests for new abstract methods**

Add to `tests/test_messaging.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_messaging.py::TestMessagingProviderNewMethods -v`
Expected: FAIL — Incomplete classes instantiate because methods aren't abstract yet

- [ ] **Step 3: Extend the base class**

Replace `shannon/messaging/providers/base.py`:

```python
"""Abstract base class for messaging providers."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine


class MessagingProvider(ABC):
    """Abstract interface for external chat platform integrations."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the messaging platform."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the messaging platform."""

    @abstractmethod
    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        """Send a message to a channel, optionally as a reply."""

    @abstractmethod
    async def send_typing(self, channel: str) -> None:
        """Show a typing indicator in the channel."""

    @abstractmethod
    async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None:
        """Add an emoji reaction to a message. Best-effort — failures should be silent."""

    @abstractmethod
    def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Register a callback for incoming messages.

        The callback signature is:
            callback(text, author, channel_id, message_id, attachments, is_reply_to_bot, is_mention)

        Where attachments is a list of dicts with keys: filename, content_type, data (bytes).
        """

    @abstractmethod
    def platform_name(self) -> str:
        """Return the unique platform identifier (e.g. 'discord')."""
```

- [ ] **Step 4: Update FakeMessagingProvider in tests to implement new methods**

Update `FakeMessagingProvider` in `tests/test_messaging.py`:

```python
class FakeMessagingProvider(MessagingProvider):
    """In-memory messaging provider for tests."""

    def __init__(self, name: str = "fake") -> None:
        self._name = name
        self._callback: Callable[..., Coroutine[Any, Any, None]] | None = None
        self.connected = False
        self.sent_messages: list[tuple[str, str, str | None]] = []
        self.typing_channels: list[str] = []
        self.reactions: list[tuple[str, str, str]] = []  # (channel, message_id, emoji)

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
    ) -> None:
        """Simulate an incoming message from this platform."""
        if self._callback is not None:
            await self._callback(
                text, author, channel_id, message_id,
                attachments or [], is_reply_to_bot, is_mention,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_messaging.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add shannon/messaging/providers/base.py tests/test_messaging.py
git commit -m "feat: extend MessagingProvider with send_typing and add_reaction"
```

---

### Task 6: DiscordProvider — Message Splitting

**Files:**
- Modify: `shannon/messaging/providers/discord.py`
- Create: `tests/test_discord_provider.py`

- [ ] **Step 1: Write failing tests for message splitting**

Create `tests/test_discord_provider.py`:

```python
"""Tests for Discord provider utilities."""

from shannon.messaging.providers.discord import split_message


class TestSplitMessage:
    def test_short_message_unchanged(self):
        assert split_message("Hello world") == ["Hello world"]

    def test_empty_message(self):
        assert split_message("") == []

    def test_exactly_2000_chars(self):
        text = "a" * 2000
        assert split_message(text) == [text]

    def test_split_on_newline(self):
        text = "a" * 1900 + "\n" + "b" * 200
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 1900
        assert chunks[1] == "b" * 200

    def test_split_on_space_when_no_newline(self):
        text = "word " * 500  # 2500 chars
        chunks = split_message(text)
        assert all(len(c) <= 2000 for c in chunks)
        assert "".join(chunks).replace(" ", "") == "word" * 500

    def test_hard_split_no_whitespace(self):
        text = "a" * 3000
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 2000
        assert chunks[1] == "a" * 1000

    def test_all_chunks_within_limit(self):
        text = "Hello world! " * 300  # ~3900 chars
        chunks = split_message(text)
        assert all(len(c) <= 2000 for c in chunks)
        assert "".join(chunks) == text.strip()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_discord_provider.py -v`
Expected: FAIL — `split_message` does not exist

- [ ] **Step 3: Implement split_message**

Add at the top of `shannon/messaging/providers/discord.py`, after imports:

```python
DISCORD_MAX_LENGTH = 2000


def split_message(text: str) -> list[str]:
    """Split text into chunks that fit within Discord's 2000-char limit.

    Splits on newlines first, then spaces, then hard-cuts as a last resort.
    """
    if not text:
        return []
    if len(text) <= DISCORD_MAX_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= DISCORD_MAX_LENGTH:
            chunks.append(remaining.strip())
            break

        # Try to split on newline
        cut = remaining.rfind("\n", 0, DISCORD_MAX_LENGTH)
        if cut == -1:
            # Try to split on space
            cut = remaining.rfind(" ", 0, DISCORD_MAX_LENGTH)
        if cut == -1:
            # Hard cut
            cut = DISCORD_MAX_LENGTH

        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip("\n ")

    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_discord_provider.py -v`
Expected: ALL PASS

- [ ] **Step 5: Update send_message to use split_message**

In `shannon/messaging/providers/discord.py`, replace the `send_message` method:

```python
    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        """Fetch the channel by ID and send a message, optionally as a reply.

        Long messages are split at 2000-char boundaries.
        """
        if self._client is None or not text:
            return

        discord_channel = self._client.get_channel(int(channel))
        if discord_channel is None:
            discord_channel = await self._client.fetch_channel(int(channel))

        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            if i == 0 and reply_to:
                try:
                    original = await discord_channel.fetch_message(int(reply_to))
                    await original.reply(chunk)
                except Exception:
                    logger.exception("Failed to reply to message %s", reply_to)
                    await discord_channel.send(chunk)
            else:
                await discord_channel.send(chunk)
```

Add `import logging` and `logger = logging.getLogger(__name__)` at the top of the file.

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add shannon/messaging/providers/discord.py tests/test_discord_provider.py
git commit -m "feat: add message splitting for Discord 2000-char limit"
```

---

### Task 7: DiscordProvider — Typing, Reactions, Attachments, Bot Filtering

**Files:**
- Modify: `shannon/messaging/providers/discord.py`
- Modify: `tests/test_discord_provider.py`

- [ ] **Step 1: Implement send_typing and add_reaction**

Add these methods to the `DiscordProvider` class in `shannon/messaging/providers/discord.py`:

```python
    async def send_typing(self, channel: str) -> None:
        """Show typing indicator in the channel."""
        if self._client is None:
            return
        discord_channel = self._client.get_channel(int(channel))
        if discord_channel is None:
            discord_channel = await self._client.fetch_channel(int(channel))
        await discord_channel.typing()

    async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None:
        """Add an emoji reaction to a message. Best-effort — failures are logged and ignored."""
        if self._client is None:
            return
        try:
            discord_channel = self._client.get_channel(int(channel))
            if discord_channel is None:
                discord_channel = await self._client.fetch_channel(int(channel))
            message = await discord_channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
        except Exception:
            logger.debug("Failed to add reaction %s to %s", emoji, message_id)
```

- [ ] **Step 2: Update on_message handler with bot filtering, attachments, and mention detection**

Replace the `connect` method's `on_message` handler and the `on_message` registration method:

```python
    async def connect(self) -> None:
        """Create a discord.Client and start it in the background."""
        import asyncio
        import discord  # type: ignore[import]

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore messages from any bot.
            if message.author.bot:
                return
            if self._callback is not None:
                # Download attachments
                attachments: list[dict] = []
                for att in message.attachments:
                    try:
                        data = await att.read()
                        attachments.append({
                            "filename": att.filename,
                            "content_type": att.content_type or "",
                            "data": data,
                        })
                    except Exception:
                        logger.debug("Failed to download attachment %s", att.filename)

                # Detect reply-to-bot
                is_reply_to_bot = False
                if message.reference and message.reference.resolved:
                    ref = message.reference.resolved
                    if isinstance(ref, discord.Message) and ref.author == self._client.user:
                        is_reply_to_bot = True

                # Detect mention
                is_mention = (
                    self._client.user is not None
                    and self._client.user.mentioned_in(message)
                )

                await self._callback(
                    message.content,
                    str(message.author),
                    str(message.channel.id),
                    str(message.id),
                    attachments,
                    is_reply_to_bot,
                    is_mention,
                )

        # Start the client in the background without blocking.
        asyncio.ensure_future(self._client.start(self._token))
```

- [ ] **Step 3: Add error handling to send_message with warning reaction**

Update the `send_message` method to add error handling — add a warning reaction on failure when a reply_to message is available. This is already partially done in Task 6. Verify the `except Exception` block in the reply path logs properly. No additional changes needed if Task 6 was implemented correctly.

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/providers/discord.py
git commit -m "feat: add typing, reactions, attachments, and bot filtering to Discord provider"
```

---

### Task 8: MessagingManager — Behavioral Logic

**Files:**
- Modify: `shannon/messaging/manager.py`
- Modify: `tests/test_messaging.py`

- [ ] **Step 1: Write failing tests for debouncing**

Add to `tests/test_messaging.py`:

```python
import asyncio
from shannon.config import MessagingConfig


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

    # Should not be published immediately
    assert len(received) == 0

    # Wait for debounce to complete
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
    # Only the second message should be published
    assert len(received) == 1
    assert received[0].text == "second"
```

- [ ] **Step 2: Write failing tests for should_respond logic**

Add to `tests/test_messaging.py`:

```python
@pytest.mark.asyncio
async def test_manager_responds_to_mention():
    """Manager should respond when message has is_mention=True."""
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
    """Manager should respond when message is a reply to bot."""
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
    """Manager should not respond to messages with no mention, reply, or active conversation."""
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
```

- [ ] **Step 3: Write failing tests for conversation continuity**

Add to `tests/test_messaging.py`:

```python
@pytest.mark.asyncio
async def test_manager_conversation_continuity():
    """Manager should respond to follow-up messages after a recent response."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, conversation_expiry=10.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []

    async def capture(event: ChatMessage):
        received.append(event)

    bus.subscribe(ChatMessage, capture)

    # Simulate a response having been sent (manually set last_response)
    manager._last_response["discord:chan"] = __import__("time").time()

    await provider.simulate_message("follow up", "user", "chan", "msg2")
    await asyncio.sleep(0.05)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_manager_conversation_expired():
    """Manager should not respond to follow-ups after conversation_expiry."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0, conversation_expiry=0.01)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    received: list[ChatMessage] = []

    async def capture(event: ChatMessage):
        received.append(event)

    bus.subscribe(ChatMessage, capture)

    # Set response time far in the past
    manager._last_response["discord:chan"] = 0.0

    await provider.simulate_message("too late", "user", "chan", "msg2")
    await asyncio.sleep(0.05)
    assert len(received) == 0
```

- [ ] **Step 4: Write failing test for response timestamp tracking**

Add to `tests/test_messaging.py`:

```python
from shannon.events import ChatReaction


@pytest.mark.asyncio
async def test_manager_tracks_response_timestamp():
    """ChatResponse should update _last_response for the channel."""
    bus = EventBus()
    provider = FakeMessagingProvider("discord")
    config = MessagingConfig(debounce_delay=0.0)
    manager = MessagingManager(bus, [provider], config)
    await manager.start()

    assert "discord:chan" not in manager._last_response

    await bus.publish(ChatResponse(text="hi", platform="discord", channel="chan"))

    assert "discord:chan" in manager._last_response


@pytest.mark.asyncio
async def test_manager_routes_reactions():
    """ChatResponse with reactions should call add_reaction on the provider."""
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
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_messaging.py::test_manager_debounce_delays_publish tests/test_messaging.py::test_manager_debounce_cancels_previous tests/test_messaging.py::test_manager_responds_to_mention tests/test_messaging.py::test_manager_responds_to_reply tests/test_messaging.py::test_manager_ignores_unrelated_message tests/test_messaging.py::test_manager_conversation_continuity tests/test_messaging.py::test_manager_conversation_expired tests/test_messaging.py::test_manager_tracks_response_timestamp tests/test_messaging.py::test_manager_routes_reactions -v`
Expected: FAIL

- [ ] **Step 6: Implement the new MessagingManager**

Replace `shannon/messaging/manager.py`:

```python
"""MessagingManager — bridges external chat platforms to the event bus."""

from __future__ import annotations

import asyncio
import logging
import random
from time import time
from typing import TYPE_CHECKING

from shannon.config import MessagingConfig
from shannon.events import ChatMessage, ChatReaction, ChatResponse

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.messaging.providers.base import MessagingProvider

logger = logging.getLogger(__name__)


class MessagingManager:
    """Connects messaging providers to the event bus.

    Incoming messages from any provider are evaluated for response eligibility
    (mentions, replies, active conversations, random chance) and debounced
    before being published as ``ChatMessage`` events.

    ``ChatResponse`` events on the bus are routed back to the correct provider,
    with reactions applied.
    """

    def __init__(
        self,
        bus: "EventBus",
        providers: list["MessagingProvider"],
        config: MessagingConfig | None = None,
    ) -> None:
        self._bus = bus
        self._providers: dict[str, "MessagingProvider"] = {
            p.platform_name(): p for p in providers
        }
        self._config = config or MessagingConfig()
        self._pending: dict[str, asyncio.Task] = {}
        self._last_response: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect all providers, register handlers, and subscribe to the bus."""
        for provider in self._providers.values():
            def _make_handler(p: "MessagingProvider"):
                async def _on_message(
                    text: str,
                    author: str,
                    channel_id: str,
                    message_id: str,
                    attachments: list[dict] | None = None,
                    is_reply_to_bot: bool = False,
                    is_mention: bool = False,
                ) -> None:
                    await self._handle_incoming(
                        platform=p.platform_name(),
                        text=text,
                        author=author,
                        channel_id=channel_id,
                        message_id=message_id,
                        attachments=attachments or [],
                        is_reply_to_bot=is_reply_to_bot,
                        is_mention=is_mention,
                    )
                return _on_message

            provider.on_message(_make_handler(provider))
            await provider.connect()

        self._bus.subscribe(ChatResponse, self._on_chat_response)

    async def stop(self) -> None:
        """Disconnect all providers, cancel pending tasks, and unsubscribe."""
        self._bus.unsubscribe(ChatResponse, self._on_chat_response)
        for task in self._pending.values():
            task.cancel()
        self._pending.clear()
        for provider in self._providers.values():
            await provider.disconnect()

    # ------------------------------------------------------------------
    # Incoming message handling
    # ------------------------------------------------------------------

    def _should_respond(
        self,
        platform: str,
        channel_id: str,
        is_reply_to_bot: bool,
        is_mention: bool,
    ) -> bool:
        """Decide whether the bot should respond to this message."""
        if is_mention or is_reply_to_bot:
            return True

        # Active conversation check
        key = f"{platform}:{channel_id}"
        last = self._last_response.get(key)
        if last is not None:
            elapsed = time() - last
            if elapsed < self._config.conversation_expiry:
                return True

        # Random reply chance
        if self._config.reply_probability > 0 and random.random() < self._config.reply_probability:
            return True

        return False

    async def _handle_incoming(
        self,
        platform: str,
        text: str,
        author: str,
        channel_id: str,
        message_id: str,
        attachments: list[dict],
        is_reply_to_bot: bool,
        is_mention: bool,
    ) -> None:
        """Evaluate response eligibility and debounce before publishing."""
        if not self._should_respond(platform, channel_id, is_reply_to_bot, is_mention):
            # Maybe react even if not responding
            if self._config.reaction_probability > 0 and random.random() < self._config.reaction_probability:
                await self._bus.publish(
                    ChatReaction(emoji="", platform=platform, channel=channel_id, message_id=message_id)
                )
            return

        key = f"{platform}:{channel_id}"

        # Cancel existing debounce task for this channel
        existing = self._pending.get(key)
        if existing and not existing.done():
            existing.cancel()

        event = ChatMessage(
            text=text,
            author=author,
            platform=platform,
            channel=channel_id,
            message_id=message_id,
            attachments=attachments,
            is_reply_to_bot=is_reply_to_bot,
            is_mention=is_mention,
        )

        async def _debounced_publish() -> None:
            try:
                if self._config.debounce_delay > 0:
                    # Show typing during debounce
                    provider = self._providers.get(platform)
                    if provider:
                        try:
                            await provider.send_typing(channel_id)
                        except Exception:
                            pass
                    await asyncio.sleep(self._config.debounce_delay)
                await self._bus.publish(event)
            except asyncio.CancelledError:
                pass
            finally:
                self._pending.pop(key, None)

        task = asyncio.create_task(_debounced_publish())
        self._pending[key] = task

    # ------------------------------------------------------------------
    # Outgoing response handling
    # ------------------------------------------------------------------

    async def _on_chat_response(self, event: ChatResponse) -> None:
        """Route a ChatResponse to the appropriate provider and track timing."""
        provider = self._providers.get(event.platform)
        if provider is None:
            return

        # Track response time for conversation continuity
        key = f"{event.platform}:{event.channel}"
        self._last_response[key] = time()

        # Send message
        reply_to = event.reply_to if event.reply_to else None
        await provider.send_message(event.channel, event.text, reply_to=reply_to)

        # Apply reactions
        if event.reactions and event.reply_to:
            for emoji in event.reactions:
                await provider.add_reaction(event.channel, event.reply_to, emoji)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_messaging.py -v`
Expected: ALL PASS

- [ ] **Step 8: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS — note that `test_app.py` and `test_integration.py` may need `MessagingManager` constructor updated if they pass `config`. Check and fix if needed.

- [ ] **Step 9: Commit**

```bash
git add shannon/messaging/manager.py tests/test_messaging.py
git commit -m "feat: add debouncing, conversation continuity, and reaction routing to MessagingManager"
```

---

### Task 9: Anthropic API — Message Normalization

**Files:**
- Modify: `shannon/brain/claude.py`
- Modify: `tests/test_claude_client.py`

- [ ] **Step 1: Write failing tests for message normalization**

Add to `tests/test_claude_client.py`:

```python
class TestNormalizeMessages:
    def test_consecutive_user_messages_merged(self):
        client = make_client()
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="user", content="How are you?"),
        ]
        _, api_messages = client._build_messages(messages)
        assert len(api_messages) == 1
        assert api_messages[0]["role"] == "user"
        assert "Hello" in api_messages[0]["content"]
        assert "How are you?" in api_messages[0]["content"]

    def test_consecutive_assistant_messages_merged(self):
        client = make_client()
        messages = [
            LLMMessage(role="user", content="Hi"),
            LLMMessage(role="assistant", content="Hello!"),
            LLMMessage(role="assistant", content="How can I help?"),
        ]
        _, api_messages = client._build_messages(messages)
        assert len(api_messages) == 2
        assert api_messages[0]["role"] == "user"
        assert api_messages[1]["role"] == "assistant"
        assert "Hello!" in api_messages[1]["content"]
        assert "How can I help?" in api_messages[1]["content"]

    def test_alternating_messages_unchanged(self):
        client = make_client()
        messages = [
            LLMMessage(role="user", content="Hi"),
            LLMMessage(role="assistant", content="Hello"),
            LLMMessage(role="user", content="Bye"),
        ]
        _, api_messages = client._build_messages(messages)
        assert len(api_messages) == 3

    def test_normalization_skips_non_string_content(self):
        """Content blocks (from compaction) should not be merged."""
        client = make_client()
        blocks = [{"type": "text", "text": "compacted"}]
        messages = [
            LLMMessage(role="assistant", content=blocks),
            LLMMessage(role="assistant", content="More text"),
        ]
        _, api_messages = client._build_messages(messages)
        # Non-string content can't be merged — should remain separate
        assert len(api_messages) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_claude_client.py::TestNormalizeMessages -v`
Expected: FAIL — consecutive messages not merged

- [ ] **Step 3: Implement _normalize_messages**

In `shannon/brain/claude.py`, add this method to `ClaudeClient` and call it at the end of `_build_messages`:

```python
    @staticmethod
    def _normalize_messages(api_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge consecutive same-role messages to ensure strict alternation.

        Only merges messages where both have string content.
        """
        if not api_messages:
            return api_messages

        merged: list[dict[str, Any]] = [api_messages[0]]
        for msg in api_messages[1:]:
            prev = merged[-1]
            if (
                prev["role"] == msg["role"]
                and isinstance(prev["content"], str)
                and isinstance(msg["content"], str)
            ):
                merged[-1] = {
                    "role": msg["role"],
                    "content": prev["content"] + "\n" + msg["content"],
                }
            else:
                merged.append(msg)

        return merged
```

Then in `_build_messages`, change the return statement from:

```python
        return system_blocks, api_messages
```

to:

```python
        return system_blocks, self._normalize_messages(api_messages)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_claude_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/brain/claude.py tests/test_claude_client.py
git commit -m "feat: add message role normalization to ClaudeClient"
```

---

### Task 10: Tool Registry — Rate Limit Server-Side Tools

**Files:**
- Modify: `shannon/brain/tool_registry.py:49-50`
- Modify: `tests/test_tool_registry.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tool_registry.py`:

```python
def test_web_search_has_max_uses():
    """web_search tool should have max_uses set."""
    config = ShannonConfig()
    registry = ToolRegistry(config)
    tools = registry.build()
    ws = next(t for t in tools if t.get("name") == "web_search")
    assert ws["max_uses"] == 3


def test_web_fetch_has_max_uses():
    """web_fetch tool should have max_uses set."""
    config = ShannonConfig()
    registry = ToolRegistry(config)
    tools = registry.build()
    wf = next(t for t in tools if t.get("name") == "web_fetch")
    assert wf["max_uses"] == 3


def test_code_execution_no_max_uses():
    """code_execution should NOT have max_uses (it's self-contained)."""
    config = ShannonConfig()
    registry = ToolRegistry(config)
    tools = registry.build()
    ce = next(t for t in tools if t.get("name") == "code_execution")
    assert "max_uses" not in ce
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tool_registry.py::test_web_search_has_max_uses tests/test_tool_registry.py::test_web_fetch_has_max_uses tests/test_tool_registry.py::test_code_execution_no_max_uses -v`
Expected: FAIL for web_search and web_fetch (no max_uses), PASS for code_execution

- [ ] **Step 3: Add max_uses to web_search and web_fetch**

In `shannon/brain/tool_registry.py`, change lines 49-50 from:

```python
        tools.append({"type": "web_search_20260209", "name": "web_search"})
        tools.append({"type": "web_fetch_20260209", "name": "web_fetch"})
```

to:

```python
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3})
        tools.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tool_registry.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add shannon/brain/tool_registry.py tests/test_tool_registry.py
git commit -m "feat: add max_uses rate limit to web_search and web_fetch tools"
```

---

### Task 11: Wire MessagingConfig Through app.py

**Files:**
- Modify: `shannon/app.py` (pass `config.messaging` to `MessagingManager` constructor)
- Modify: `tests/test_integration.py` (if it constructs `MessagingManager`)

- [ ] **Step 1: Read app.py to find the MessagingManager construction**

Read `shannon/app.py` and find where `MessagingManager` is instantiated. It should be something like:

```python
manager = MessagingManager(bus, [provider])
```

Change it to:

```python
manager = MessagingManager(bus, [provider], config.messaging)
```

- [ ] **Step 2: Read test_integration.py for any MessagingManager construction**

If `test_integration.py` constructs `MessagingManager`, update it to pass a `MessagingConfig()` or verify the default `None` parameter works.

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add shannon/app.py tests/test_integration.py
git commit -m "feat: wire MessagingConfig through to MessagingManager in app.py"
```

---

### Task 12: Final Integration Test

**Files:**
- Modify: `tests/test_messaging.py`

- [ ] **Step 1: Write an end-to-end integration test**

Add to `tests/test_messaging.py`:

```python
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

    # Verify conversation continuity is tracked
    assert "discord:chan1" in manager._last_response

    await manager.stop()
```

- [ ] **Step 2: Run it**

Run: `python3 -m pytest tests/test_messaging.py::test_full_flow_mention_debounce_react -v`
Expected: PASS

- [ ] **Step 3: Run the complete test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_messaging.py
git commit -m "test: add end-to-end integration test for messaging flow"
```
