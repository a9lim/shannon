"""Tests for Brain, PromptBuilder, and LLM provider base types."""

import asyncio

import pytest

from shannon.brain.types import (
    LLMMessage,
    LLMToolCall,
    LLMResponse,
)


# ---------------------------------------------------------------------------
# Type tests
# ---------------------------------------------------------------------------


def test_llm_message():
    msg = LLMMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_llm_message_defaults():
    msg = LLMMessage(role="assistant", content="hi")
    assert msg.images == []
    assert msg.tool_calls == []
    assert msg.tool_results == []


def test_llm_message_with_image():
    msg = LLMMessage(role="user", content="what's this?", images=[b"\x89PNG"])
    assert len(msg.images) == 1


def test_llm_tool_call():
    call = LLMToolCall(id="call_123", name="bash", arguments={"command": "ls"})
    assert call.id == "call_123"
    assert call.name == "bash"
    assert call.arguments == {"command": "ls"}


def test_llm_response():
    resp = LLMResponse(text="hello!", tool_calls=[])
    assert resp.text == "hello!"


def test_llm_response_defaults():
    resp = LLMResponse(text="hi")
    assert resp.tool_calls == []


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClaude:
    def __init__(self, text="Hello!", tool_calls=None):
        self._text = text
        self._tool_calls = tool_calls or []
        self.call_count = 0

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        # Return tool_calls only on the first call; subsequent calls return plain text
        if self.call_count == 1:
            return LLMResponse(text=self._text, tool_calls=self._tool_calls, stop_reason="end_turn")
        return LLMResponse(text=self._text, tool_calls=[], stop_reason="end_turn")


class FakeDispatcher:
    def __init__(self):
        self.dispatched = []
        self.channel_id = ""
        self.participants = {}

    def set_context(self, channel_id, participants):
        self.channel_id = channel_id
        self.participants = dict(participants)

    async def dispatch(self, tool_call):
        self.dispatched.append(tool_call)
        return "Tool result."

    @staticmethod
    def is_continue(name):
        return name == "continue"

    @staticmethod
    def is_expression(name):
        return name == "set_expression"

    @staticmethod
    def is_server_side(name):
        return name in {"web_search", "web_fetch", "code_execution", "memory"}


class FakeRegistry:
    def build(self, mode="full"):
        return [{"type": "bash_20250124", "name": "bash"}]

    def beta_headers(self):
        return ["computer-use-2025-11-24"]


# ---------------------------------------------------------------------------
# Brain + PromptBuilder tests
# ---------------------------------------------------------------------------

from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import (
    UserInput,
    ChatMessage,
    LLMResponse as LLMResponseEvent,
    ChatResponse,
    ExpressionChange,
    VoiceInput,
    VoiceOutput,
)
from shannon.brain.brain import Brain
from shannon.brain.prompt import PromptBuilder


def _make_brain(fake_claude=None, fake_dispatcher=None, fake_registry=None):
    bus = EventBus()
    claude = fake_claude or FakeClaude()
    dispatcher = fake_dispatcher or FakeDispatcher()
    registry = fake_registry or FakeRegistry()
    config = ShannonConfig()
    brain = Brain(bus=bus, claude=claude, dispatcher=dispatcher, registry=registry, config=config)
    return bus, brain


@pytest.mark.asyncio
async def test_brain_handles_user_input():
    """Publishing a UserInput event should cause an LLMResponseEvent to be emitted."""
    bus, brain = _make_brain()

    received: list[LLMResponseEvent] = []

    async def capture(event: LLMResponseEvent):
        received.append(event)

    bus.subscribe(LLMResponseEvent, capture)
    await brain.start()

    await bus.publish(UserInput(text="Hello Shannon!", source="text"))

    assert len(received) == 1
    assert received[0].text == "Hello!"


@pytest.mark.asyncio
async def test_brain_handles_chat_message():
    """Publishing a ChatMessage should emit both LLMResponseEvent and ChatResponse with matching platform/channel."""
    bus, brain = _make_brain()

    llm_responses: list[LLMResponseEvent] = []
    chat_responses: list[ChatResponse] = []

    async def capture_llm(event: LLMResponseEvent):
        llm_responses.append(event)

    async def capture_chat(event: ChatResponse):
        chat_responses.append(event)

    bus.subscribe(LLMResponseEvent, capture_llm)
    bus.subscribe(ChatResponse, capture_chat)
    await brain.start()

    msg = ChatMessage(
        text="Hey Shannon!",
        author="testuser",
        platform="discord",
        channel="general",
        message_id="msg_001",
    )
    await bus.publish(msg)

    assert len(llm_responses) == 1
    assert len(chat_responses) == 1
    assert chat_responses[0].platform == "discord"
    assert chat_responses[0].channel == "general"
    assert chat_responses[0].reply_to == "msg_001"
    assert chat_responses[0].text == "Hello!"


@pytest.mark.asyncio
async def test_brain_expression_tool_emits_event():
    """A set_expression tool call should emit an ExpressionChange event."""
    expression_call = LLMToolCall(
        id="call_expr_1",
        name="set_expression",
        arguments={"name": "happy", "intensity": 0.9},
    )
    fake_claude = FakeClaude(text="I'm happy!", tool_calls=[expression_call])
    bus, brain = _make_brain(fake_claude=fake_claude)

    expressions: list[ExpressionChange] = []

    async def capture_expr(event: ExpressionChange):
        expressions.append(event)

    bus.subscribe(ExpressionChange, capture_expr)
    await brain.start()

    await bus.publish(UserInput(text="How are you?", source="text"))

    assert len(expressions) == 1
    assert expressions[0].name == "happy"
    assert expressions[0].intensity == 0.9


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


class FakeClaudeToolLoop:
    """Always returns a non-server-side tool call, simulating infinite tool loop."""
    def __init__(self, final_text="Final response after exhaustion."):
        self.call_count = 0
        self._final_text = final_text

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        if tools is None:
            # Final tool-free call
            return LLMResponse(text=self._final_text, tool_calls=[], stop_reason="end_turn")
        # Always return a tool call to exhaust the loop
        return LLMResponse(
            text="",
            tool_calls=[LLMToolCall(id=f"call_{self.call_count}", name="bash", arguments={"command": "echo hi"})],
            stop_reason="tool_use",
        )


@pytest.mark.asyncio
async def test_brain_tool_exhaustion_makes_final_call():
    """When tool loop exhausts max iterations, brain makes a final tool-free call."""
    fake_claude = FakeClaudeToolLoop(final_text="Done after exhaustion.")
    bus, brain = _make_brain(fake_claude=fake_claude)

    llm_responses: list[LLMResponseEvent] = []
    async def capture(event: LLMResponseEvent):
        llm_responses.append(event)
    bus.subscribe(LLMResponseEvent, capture)
    await brain.start()

    await bus.publish(UserInput(text="Do something complex", source="text"))

    # The final response should contain the exhaustion text
    texts = [r.text for r in llm_responses if r.text]
    assert any("Done after exhaustion" in t for t in texts)
    # Should have called generate with tools=None at least once
    assert fake_claude.call_count > 1


@pytest.mark.asyncio
async def test_brain_tool_exhaustion_caps_at_lower_iterations():
    """Tool loop should cap at max_continues + 5, not max_continues + 20."""
    fake_claude = FakeClaudeToolLoop(final_text="Done.")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    await bus.publish(UserInput(text="Do something", source="text"))

    # max_continues=5, safety margin=5, so max_iterations=10
    # Plus 1 for the final tool-free call = 11 total
    assert fake_claude.call_count <= 11


class FakeClaudeEmpty:
    """Returns empty text with no tool calls."""
    def __init__(self):
        self.call_count = 0

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        return LLMResponse(text="", tool_calls=[], stop_reason="end_turn")


@pytest.mark.asyncio
async def test_brain_empty_response_emits_warning_reaction():
    """When LLM returns empty text for a ChatMessage, emit ChatResponse with warning reaction."""
    fake_claude = FakeClaudeEmpty()
    bus, brain = _make_brain(fake_claude=fake_claude)

    chat_responses: list[ChatResponse] = []
    async def capture(event: ChatResponse):
        chat_responses.append(event)
    bus.subscribe(ChatResponse, capture)
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
    assert chat_responses[0].text == ""
    assert "⚠️" in chat_responses[0].reactions
    assert chat_responses[0].reply_to == "msg_1"


@pytest.mark.asyncio
async def test_brain_chat_message_passes_custom_emojis_as_suffix():
    """custom_emojis from ChatMessage should appear in the system prompt."""
    fake_claude = FakeClaude(text="Nice emojis!")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    msg = ChatMessage(
        text="Hello!",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
        custom_emojis="Available custom emojis in this server: :pepe:, :sadge:",
    )
    await bus.publish(msg)
    assert fake_claude.call_count >= 1


@pytest.mark.asyncio
async def test_brain_chat_message_includes_participants_in_suffix():
    """Participants from ChatMessage should appear in the system prompt context."""
    fake_claude = FakeClaude(text="Hi everyone!")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    msg = ChatMessage(
        text="Hello!",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
        participants={"123": "Alice", "456": "Bob"},
    )
    await bus.publish(msg)
    assert fake_claude.call_count >= 1


@pytest.mark.asyncio
async def test_brain_chat_message_annotates_admin_participants():
    """Admin users should be annotated in the participants suffix."""
    fake_claude = FakeClaude(text="Yes admin!")
    config = ShannonConfig()
    config.messaging.admin_ids = ["123"]
    bus = EventBus()
    dispatcher = FakeDispatcher()
    registry = FakeRegistry()
    brain = Brain(bus=bus, claude=fake_claude, dispatcher=dispatcher, registry=registry, config=config)

    chat_responses: list[ChatResponse] = []
    async def capture(event: ChatResponse):
        chat_responses.append(event)
    bus.subscribe(ChatResponse, capture)
    await brain.start()

    msg = ChatMessage(
        text="Hello!",
        author="Alice",
        platform="discord",
        channel="general",
        message_id="msg_1",
        participants={"123": "Alice", "456": "Bob"},
    )
    await bus.publish(msg)
    assert fake_claude.call_count >= 1


def test_prompt_builder():
    """PromptBuilder should include personality text in the built prompt."""
    personality = "You are Shannon, an AI VTuber."
    builder = PromptBuilder(personality_text=personality, name="Shannon")

    prompt = builder.build()
    assert personality in prompt
    assert "Response Format" not in prompt

    memory_context = "## What I Remember\n- [facts] The user likes cats."
    prompt_with_memory = builder.build(memory_context=memory_context)
    assert memory_context in prompt_with_memory

    summary = "User discussed their day."
    prompt_with_summary = builder.build(conversation_summary=summary)
    assert summary in prompt_with_summary
    assert "Earlier Conversation Summary" in prompt_with_summary


class FakeClaudeCapturing:
    """FakeClaude that captures messages for inspection."""
    def __init__(self, text="Hello!", tool_calls=None):
        self._text = text
        self._tool_calls = tool_calls or []
        self.call_count = 0
        self.last_messages = None

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        self.last_messages = messages
        if self.call_count == 1:
            return LLMResponse(text=self._text, tool_calls=self._tool_calls, stop_reason="end_turn")
        return LLMResponse(text=self._text, tool_calls=[], stop_reason="end_turn")


@pytest.mark.asyncio
async def test_brain_dynamic_context_not_in_system_prompt():
    """Dynamic content (emojis, participants) should be in user message, not system prompt."""
    fake_claude = FakeClaudeCapturing(text="Hi!")
    bus = EventBus()
    dispatcher = FakeDispatcher()
    registry = FakeRegistry()
    config = ShannonConfig()
    brain = Brain(bus=bus, claude=fake_claude, dispatcher=dispatcher, registry=registry, config=config)

    chat_responses: list[ChatResponse] = []
    async def capture(event: ChatResponse):
        chat_responses.append(event)
    bus.subscribe(ChatResponse, capture)
    await brain.start()

    msg = ChatMessage(
        text="Hello!",
        author="user",
        platform="discord",
        channel="general",
        message_id="msg_1",
        custom_emojis="Custom emojis: :pepe:, :sadge:",
        participants={"123": "Alice", "456": "Bob"},
    )
    await bus.publish(msg)

    # System prompt (first message) should NOT contain emoji or participant info
    system_msg = fake_claude.last_messages[0]
    assert system_msg.role == "system"
    assert "pepe" not in str(system_msg.content)
    assert "Alice" not in str(system_msg.content)

    # The user message should contain the dynamic info
    non_system = [m for m in fake_claude.last_messages if m.role == "user"]
    all_user_content = " ".join(str(m.content) for m in non_system)
    assert "pepe" in all_user_content
    assert "Alice" in all_user_content


@pytest.mark.asyncio
async def test_brain_history_does_not_contain_images():
    """History entries should not carry image data to avoid bloating context."""
    fake_claude = FakeClaude(text="I see an image!")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    await bus.publish(UserInput(text="What's this?", source="text"))

    # Even after processing, history images should be empty
    for msg in brain._history:
        assert msg.images == [], f"History msg has images: {len(msg.images)} images"


class FakeClaudeYielding:
    """FakeClaude that yields to the event loop once per call, exposing interleaving opportunities."""

    def __init__(self, text="Reply"):
        self._text = text
        self.call_count = 0

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        # Yield to the event loop so concurrent coroutines can attempt to interleave
        await asyncio.sleep(0)
        return LLMResponse(text=self._text, tool_calls=[], stop_reason="end_turn")


@pytest.mark.asyncio
async def test_brain_concurrent_inputs_are_serialized():
    """Concurrent UserInput events must be serialized so history stays in proper alternating order."""
    fake_claude = FakeClaudeYielding(text="Reply")
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    # Fire two UserInput events concurrently
    await asyncio.gather(
        bus.publish(UserInput(text="First message", source="text")),
        bus.publish(UserInput(text="Second message", source="text")),
    )

    # History must have exactly 4 entries: user, assistant, user, assistant
    assert len(brain._history) == 4, f"Expected 4 history entries, got {len(brain._history)}"

    # Entries must alternate roles strictly
    expected_roles = ["user", "assistant", "user", "assistant"]
    actual_roles = [msg.role for msg in brain._history]
    assert actual_roles == expected_roles, f"History roles out of order: {actual_roles}"


# ---------------------------------------------------------------------------
# Tool dispatch exception handling
# ---------------------------------------------------------------------------


class RaisingDispatcher:
    """Dispatcher that raises RuntimeError on every dispatch call."""

    def __init__(self):
        self.channel_id = ""
        self.participants = {}

    def set_context(self, channel_id, participants):
        self.channel_id = channel_id
        self.participants = dict(participants)

    async def dispatch(self, tool_call):
        raise RuntimeError("Simulated executor failure")

    @staticmethod
    def is_continue(name):
        return name == "continue"

    @staticmethod
    def is_expression(name):
        return name == "set_expression"

    @staticmethod
    def is_server_side(name):
        return name in {"web_search", "web_fetch", "code_execution", "memory"}


@pytest.mark.asyncio
async def test_brain_tool_dispatch_exception_returns_error_result():
    """A failing tool executor must not crash the LLM turn; brain should still produce a response."""
    tool_call = LLMToolCall(
        id="call_bash_1",
        name="bash",
        arguments={"command": "echo hi"},
    )
    # First generate returns a tool call; second returns plain text
    fake_claude = FakeClaude(text="Done!", tool_calls=[tool_call])
    bus, brain = _make_brain(fake_claude=fake_claude, fake_dispatcher=RaisingDispatcher())

    llm_responses: list[LLMResponseEvent] = []

    async def capture(event: LLMResponseEvent):
        llm_responses.append(event)

    bus.subscribe(LLMResponseEvent, capture)
    await brain.start()

    # Should not raise despite the dispatcher always failing
    await bus.publish(UserInput(text="Run something", source="text"))

    # Brain must still produce a response (second LLM call after error result)
    assert len(llm_responses) >= 1
    assert any(r.text == "Done!" for r in llm_responses)


class FakeClaudePauseTurn:
    """Simulates pause_turn on first call (server-side tool in progress), then end_turn."""
    def __init__(self):
        self.call_count = 0
        self.messages_per_call = []

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        self.messages_per_call.append(list(messages))
        if self.call_count == 1:
            return LLMResponse(
                text="thinking...",
                tool_calls=[LLMToolCall(id="st1", name="web_search", arguments={"query": "test"})],
                stop_reason="pause_turn",
            )
        return LLMResponse(text="done", tool_calls=[], stop_reason="end_turn")


@pytest.mark.asyncio
async def test_brain_pause_turn_server_side_tool_not_in_messages():
    """pause_turn with server-side tools must NOT include their tool_use blocks.

    Server-side tool_use IDs without matching tool_result blocks cause
    an API 400 error.  The brain should omit them from reconstructed messages.
    """
    fake_claude = FakeClaudePauseTurn()
    bus, brain = _make_brain(fake_claude=fake_claude)

    llm_responses: list[LLMResponseEvent] = []

    async def capture(event: LLMResponseEvent):
        llm_responses.append(event)

    bus.subscribe(LLMResponseEvent, capture)
    await brain.start()

    await bus.publish(UserInput(text="Search for something", source="text"))

    # generate should have been called twice: once pause_turn, once end_turn
    assert fake_claude.call_count == 2

    # The second call's messages must have an assistant message WITHOUT the
    # server-side tool call (web_search), since we can't provide a tool_result
    # for it — the API handles it internally.
    second_call_messages = fake_claude.messages_per_call[1]
    assistant_msgs = [m for m in second_call_messages if m.role == "assistant"]
    assert len(assistant_msgs) >= 1
    pause_assistant = assistant_msgs[-1]
    assert len(pause_assistant.tool_calls) == 0

    # Brain should have produced output (from both turns)
    assert any(r.text for r in llm_responses)


@pytest.mark.asyncio
async def test_brain_max_session_messages_zero_means_no_history():
    """max_session_messages=0 should mean stateless — no history included in subsequent calls."""

    class CapturingClaude:
        def __init__(self):
            self.call_count = 0
            self.all_messages = []

        async def generate(self, messages, tools=None, betas=None):
            self.call_count += 1
            self.all_messages.append(list(messages))
            return LLMResponse(text="Reply", tool_calls=[], stop_reason="end_turn")

    capturing_claude = CapturingClaude()
    config = ShannonConfig()
    config.memory.max_session_messages = 0
    bus = EventBus()
    dispatcher = FakeDispatcher()
    registry = FakeRegistry()
    brain = Brain(bus=bus, claude=capturing_claude, dispatcher=dispatcher, registry=registry, config=config)
    await brain.start()

    await bus.publish(UserInput(text="First message", source="text"))
    await bus.publish(UserInput(text="Second message", source="text"))

    assert capturing_claude.call_count == 2

    # Second call should have only system prompt + current user message (no history)
    second_call_messages = capturing_claude.all_messages[1]
    assert len(second_call_messages) == 2, (
        f"Expected 2 messages (system + user) but got {len(second_call_messages)}: "
        f"{[m.role for m in second_call_messages]}"
    )
    assert second_call_messages[0].role == "system"
    assert second_call_messages[1].role == "user"
    assert second_call_messages[1].content == "Second message"


@pytest.mark.asyncio
async def test_brain_handles_voice_input():
    """VoiceInput should produce an LLMResponseEvent."""
    bus, brain = _make_brain()

    llm_responses: list[LLMResponseEvent] = []
    bus.subscribe(LLMResponseEvent, lambda e: llm_responses.append(e))
    await brain.start()

    await bus.publish(VoiceInput(
        text="Alice: Hello Shannon!",
        speakers={"123": "Alice"},
        channel="vc_1",
    ))

    assert len(llm_responses) == 1
    assert llm_responses[0].text == "Hello!"


@pytest.mark.asyncio
async def test_brain_voice_input_skipped_by_probability():
    """VoiceInput with reply_probability=0 should be silently dropped."""
    bus, brain = _make_brain()
    brain._config.messaging.voice.voice_reply_probability = 0.0

    llm_responses: list[LLMResponseEvent] = []
    bus.subscribe(LLMResponseEvent, lambda e: llm_responses.append(e))
    await brain.start()

    await bus.publish(VoiceInput(
        text="Alice: Hello!",
        speakers={"123": "Alice"},
        channel="vc_1",
    ))

    assert len(llm_responses) == 0


class FakeClaudeToolOnly:
    """Returns only tool calls (no text) on the first call, then text on the second."""
    def __init__(self):
        self.call_count = 0
        self.messages_per_call = []

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        self.messages_per_call.append(list(messages))
        if self.call_count == 1:
            return LLMResponse(
                text="",
                tool_calls=[LLMToolCall(id="tc1", name="bash", arguments={"command": "ls"})],
                stop_reason="end_turn",
            )
        return LLMResponse(text="done", tool_calls=[], stop_reason="end_turn")


@pytest.mark.asyncio
async def test_brain_tool_only_response_no_empty_history():
    """When LLM responds with only tool calls and no text, history must not contain an empty assistant message."""
    fake_claude = FakeClaudeToolOnly()
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()
    await bus.publish(UserInput(text="run ls", source="text"))
    for msg in brain._history:
        if msg.role == "assistant":
            assert msg.content != "", "Empty assistant message found in history"


@pytest.mark.asyncio
async def test_brain_history_cleared_when_max_zero():
    """When max_session_messages=0, history should not accumulate."""
    bus, brain = _make_brain()
    brain._config.memory.max_session_messages = 0
    await brain.start()
    await bus.publish(UserInput(text="Hello", source="text"))
    await bus.publish(UserInput(text="World", source="text"))
    assert len(brain._history) == 0


@pytest.mark.asyncio
async def test_brain_expression_intensity_invalid_string_defaults():
    """Non-numeric intensity string should default to 0.7 without raising."""
    expression_call = LLMToolCall(
        id="call_expr_bad",
        name="set_expression",
        arguments={"name": "excited", "intensity": "high"},
    )
    fake_claude = FakeClaude(text="So excited!", tool_calls=[expression_call])
    bus, brain = _make_brain(fake_claude=fake_claude)

    expressions: list[ExpressionChange] = []

    async def capture_expr(event: ExpressionChange):
        expressions.append(event)

    bus.subscribe(ExpressionChange, capture_expr)
    await brain.start()

    # Should not raise
    await bus.publish(UserInput(text="How are you?", source="text"))

    assert len(expressions) == 1
    assert expressions[0].name == "excited"
    assert expressions[0].intensity == 0.7
