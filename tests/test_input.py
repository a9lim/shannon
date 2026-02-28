"""Tests for the input system: text, STT, and InputManager."""

import asyncio
import pytest

from shannon.bus import EventBus
from shannon.events import UserInput
from shannon.input.providers.base import STTProvider
from shannon.input.providers.text import TextInputProvider
from shannon.input.manager import InputManager


# ---------------------------------------------------------------------------
# STTProvider ABC tests
# ---------------------------------------------------------------------------

def test_stt_provider_is_abstract():
    """STTProvider cannot be instantiated directly."""
    try:
        STTProvider()
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


def test_stt_provider_requires_transcribe():
    """A subclass missing transcribe() cannot be instantiated."""
    from typing import AsyncIterator

    class IncompleteProvider(STTProvider):
        async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
            async def _gen():
                yield ""
            return _gen()

    try:
        IncompleteProvider()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_stt_provider_requires_stream_transcribe():
    """A subclass missing stream_transcribe() cannot be instantiated."""

    class IncompleteProvider(STTProvider):
        async def transcribe(self, audio: bytes) -> str:
            return ""

    try:
        IncompleteProvider()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_stt_provider_concrete_subclass_instantiates():
    """A complete concrete subclass of STTProvider can be instantiated."""
    from typing import AsyncIterator

    class ConcreteProvider(STTProvider):
        async def transcribe(self, audio: bytes) -> str:
            return "transcribed"

        async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
            async def _gen():
                yield "transcribed"
            return _gen()

    provider = ConcreteProvider()
    assert isinstance(provider, STTProvider)


# ---------------------------------------------------------------------------
# InputManager — handle_text tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_text_emits_user_input():
    """handle_text should publish a UserInput event with source='text'."""
    bus = EventBus()
    manager = InputManager(bus)

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    await manager.handle_text("hello shannon")

    assert len(received) == 1
    assert received[0].text == "hello shannon"
    assert received[0].source == "text"


@pytest.mark.asyncio
async def test_handle_text_empty_string_ignored():
    """handle_text should not emit an event for an empty string."""
    bus = EventBus()
    manager = InputManager(bus)

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    await manager.handle_text("")

    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_text_whitespace_only_ignored():
    """handle_text should not emit an event for whitespace-only input."""
    bus = EventBus()
    manager = InputManager(bus)

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    await manager.handle_text("   \t\n  ")

    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_text_strips_whitespace():
    """handle_text should emit the stripped text."""
    bus = EventBus()
    manager = InputManager(bus)

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    await manager.handle_text("  hello  ")

    assert len(received) == 1
    assert received[0].text == "hello"


# ---------------------------------------------------------------------------
# InputManager — handle_audio tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_audio_emits_user_input_with_voice_source():
    """handle_audio should transcribe and emit UserInput with source='voice'."""
    from typing import AsyncIterator

    class FakeSTT(STTProvider):
        async def transcribe(self, audio: bytes) -> str:
            return "what time is it"

        async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
            async def _gen():
                yield "what time is it"
            return _gen()

    bus = EventBus()
    manager = InputManager(bus, stt_provider=FakeSTT())

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    await manager.handle_audio(b"\x00\x01\x02")

    assert len(received) == 1
    assert received[0].text == "what time is it"
    assert received[0].source == "voice"


@pytest.mark.asyncio
async def test_handle_audio_empty_transcription_ignored():
    """handle_audio should not emit an event if transcription is empty."""
    from typing import AsyncIterator

    class SilentSTT(STTProvider):
        async def transcribe(self, audio: bytes) -> str:
            return ""

        async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
            async def _gen():
                yield ""
            return _gen()

    bus = EventBus()
    manager = InputManager(bus, stt_provider=SilentSTT())

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    await manager.handle_audio(b"\x00\x01\x02")

    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_audio_without_stt_provider_does_nothing():
    """handle_audio without an STT provider should not raise or emit."""
    bus = EventBus()
    manager = InputManager(bus)  # no stt_provider

    received: list[UserInput] = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)
    # Should not raise
    await manager.handle_audio(b"\x00\x01\x02")

    assert len(received) == 0


# ---------------------------------------------------------------------------
# InputManager — speech mode
# ---------------------------------------------------------------------------

def test_set_speech_mode():
    """set_speech_mode should toggle without raising."""
    bus = EventBus()
    manager = InputManager(bus)
    manager.set_speech_mode(True)
    manager.set_speech_mode(False)


# ---------------------------------------------------------------------------
# TextInputProvider tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_input_provider_reads_line(monkeypatch):
    """TextInputProvider.read_line should return stripped input from stdin."""
    import io
    import sys

    fake_stdin = io.StringIO("hello world\n")
    monkeypatch.setattr(sys, "stdin", fake_stdin)

    provider = TextInputProvider()
    line = await provider.read_line()
    assert line == "hello world"


@pytest.mark.asyncio
async def test_text_input_provider_eof_returns_none(monkeypatch):
    """TextInputProvider.read_line should return None on EOF."""
    import io
    import sys

    fake_stdin = io.StringIO("")
    monkeypatch.setattr(sys, "stdin", fake_stdin)

    provider = TextInputProvider()
    line = await provider.read_line()
    assert line is None
