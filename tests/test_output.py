"""Tests for the output system: TTS providers, VTuber providers, and OutputManager."""

from __future__ import annotations

import pytest
from typing import AsyncIterator

from shannon.bus import EventBus
from shannon.events import ExpressionChange, LLMResponse, SpeechEnd, SpeechStart
from shannon.output.providers.tts.base import AudioChunk, TTSProvider
from shannon.output.providers.vtuber.base import VTuberProvider
from shannon.output.manager import OutputManager


# ---------------------------------------------------------------------------
# Fake implementations
# ---------------------------------------------------------------------------

class FakeTTS(TTSProvider):
    """In-memory TTS that records calls and returns a fixed AudioChunk."""

    def __init__(self, sample_rate: int = 22050) -> None:
        self._sample_rate = sample_rate
        self.synthesize_calls: list[str] = []
        self.phoneme_calls: list[str] = []

    async def synthesize(self, text: str) -> AudioChunk:
        self.synthesize_calls.append(text)
        # 1 second of silence (16-bit mono)
        num_samples = self._sample_rate
        data = b"\x00\x00" * num_samples
        return AudioChunk(data=data, sample_rate=self._sample_rate, channels=1)

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        chunk = await self.synthesize(text)

        async def _gen():
            yield chunk

        return _gen()

    async def get_phonemes(self, text: str) -> list[str]:
        self.phoneme_calls.append(text)
        return ["h", "e", "l", "o"]


class FakeVTuber(VTuberProvider):
    """Records all VTuber commands for test assertions."""

    def __init__(self) -> None:
        self.connected = False
        self.expressions: list[tuple[str, float]] = []
        self.speaking = False
        self.idle_animations: list[str] = []
        self.phonemes_received: list[list[str] | None] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def set_expression(self, name: str, intensity: float) -> None:
        self.expressions.append((name, intensity))

    async def start_speaking(self, phonemes: list[str] | None = None) -> None:
        self.speaking = True
        self.phonemes_received.append(phonemes)

    async def stop_speaking(self) -> None:
        self.speaking = False

    async def set_idle_animation(self, name: str) -> None:
        self.idle_animations.append(name)


# ---------------------------------------------------------------------------
# AudioChunk construction
# ---------------------------------------------------------------------------

def test_audio_chunk_defaults():
    """AudioChunk defaults channels to 1."""
    chunk = AudioChunk(data=b"\x00\x01", sample_rate=16000)
    assert chunk.data == b"\x00\x01"
    assert chunk.sample_rate == 16000
    assert chunk.channels == 1


def test_audio_chunk_explicit_channels():
    """AudioChunk stores explicit channel count."""
    chunk = AudioChunk(data=b"", sample_rate=44100, channels=2)
    assert chunk.channels == 2


# ---------------------------------------------------------------------------
# TTSProvider ABC guards
# ---------------------------------------------------------------------------

def test_tts_provider_is_abstract():
    """TTSProvider cannot be instantiated directly."""
    try:
        TTSProvider()
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


def test_tts_provider_missing_synthesize():
    """A subclass missing synthesize() cannot be instantiated."""

    class Incomplete(TTSProvider):
        async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
            async def _g():
                yield AudioChunk(data=b"", sample_rate=22050)
            return _g()

        async def get_phonemes(self, text: str) -> list[str]:
            return []

    try:
        Incomplete()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_tts_provider_concrete_subclass_instantiates():
    """A fully implemented TTSProvider subclass can be instantiated."""
    provider = FakeTTS()
    assert isinstance(provider, TTSProvider)


# ---------------------------------------------------------------------------
# VTuberProvider ABC guards
# ---------------------------------------------------------------------------

def test_vtuber_provider_is_abstract():
    """VTuberProvider cannot be instantiated directly."""
    try:
        VTuberProvider()
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


def test_vtuber_provider_missing_connect():
    """A subclass missing connect() cannot be instantiated."""

    class Incomplete(VTuberProvider):
        async def disconnect(self) -> None: ...
        async def set_expression(self, name: str, intensity: float) -> None: ...
        async def start_speaking(self, phonemes: list[str] | None = None) -> None: ...
        async def stop_speaking(self) -> None: ...
        async def set_idle_animation(self, name: str) -> None: ...

    try:
        Incomplete()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_vtuber_provider_concrete_subclass_instantiates():
    """A fully implemented VTuberProvider subclass can be instantiated."""
    vtuber = FakeVTuber()
    assert isinstance(vtuber, VTuberProvider)


# ---------------------------------------------------------------------------
# OutputManager — text mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_manager_text_mode_prints(capsys):
    """In text mode, OutputManager prints the response text to stdout."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=False)
    manager.start()

    await bus.publish(LLMResponse(text="Hello world", expressions=[], actions=[], mood="neutral"))

    captured = capsys.readouterr()
    assert "Hello world" in captured.out


@pytest.mark.asyncio
async def test_output_manager_text_mode_tts_not_called(capsys):
    """In text mode, TTS synthesize is NOT called."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=False)
    manager.start()

    await bus.publish(LLMResponse(text="Hello", expressions=[], actions=[], mood="neutral"))

    assert len(tts.synthesize_calls) == 0


# ---------------------------------------------------------------------------
# OutputManager — speech mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_manager_speech_mode_tts_called():
    """In speech mode, TTS synthesize IS called with the response text."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=True)
    manager.start()

    await bus.publish(LLMResponse(text="Speak this", expressions=[], actions=[], mood="neutral"))

    assert tts.synthesize_calls == ["Speak this"]


@pytest.mark.asyncio
async def test_output_manager_speech_mode_emits_speech_start():
    """In speech mode, SpeechStart is emitted before audio ends."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=True)
    manager.start()

    starts: list[SpeechStart] = []

    async def capture_start(e: SpeechStart) -> None:
        starts.append(e)

    bus.subscribe(SpeechStart, capture_start)

    await bus.publish(LLMResponse(text="Hello", expressions=[], actions=[], mood="neutral"))

    assert len(starts) == 1
    assert isinstance(starts[0], SpeechStart)
    assert starts[0].duration > 0


@pytest.mark.asyncio
async def test_output_manager_speech_mode_emits_speech_end():
    """In speech mode, SpeechEnd is emitted after synthesis."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=True)
    manager.start()

    ends: list[SpeechEnd] = []

    async def capture_end(e: SpeechEnd) -> None:
        ends.append(e)

    bus.subscribe(SpeechEnd, capture_end)

    await bus.publish(LLMResponse(text="Hello", expressions=[], actions=[], mood="neutral"))

    assert len(ends) == 1


@pytest.mark.asyncio
async def test_output_manager_speech_mode_speech_start_before_end():
    """SpeechStart is emitted before SpeechEnd."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=True)
    manager.start()

    order: list[str] = []

    async def capture_start(e: SpeechStart) -> None:
        order.append("start")

    async def capture_end(e: SpeechEnd) -> None:
        order.append("end")

    bus.subscribe(SpeechStart, capture_start)
    bus.subscribe(SpeechEnd, capture_end)

    await bus.publish(LLMResponse(text="Hello", expressions=[], actions=[], mood="neutral"))

    assert order == ["start", "end"]


@pytest.mark.asyncio
async def test_output_manager_speech_mode_phonemes_passed_to_vtuber():
    """In speech mode with a VTuber provider, phonemes are passed to start_speaking."""
    bus = EventBus()
    tts = FakeTTS()
    vtuber = FakeVTuber()
    manager = OutputManager(bus, tts_provider=tts, vtuber_provider=vtuber, speech_output=True)
    manager.start()

    await bus.publish(LLMResponse(text="Hello", expressions=[], actions=[], mood="neutral"))

    assert len(vtuber.phonemes_received) == 1
    assert vtuber.phonemes_received[0] == ["h", "e", "l", "o"]


@pytest.mark.asyncio
async def test_output_manager_speech_mode_vtuber_stop_speaking_called():
    """After synthesis, the VTuber's stop_speaking is called."""
    bus = EventBus()
    tts = FakeTTS()
    vtuber = FakeVTuber()
    manager = OutputManager(bus, tts_provider=tts, vtuber_provider=vtuber, speech_output=True)
    manager.start()

    await bus.publish(LLMResponse(text="Hello", expressions=[], actions=[], mood="neutral"))

    assert not vtuber.speaking  # stop_speaking was called


# ---------------------------------------------------------------------------
# OutputManager — expression forwarding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_manager_forwards_expression_to_vtuber():
    """ExpressionChange events are forwarded to the VTuber provider."""
    bus = EventBus()
    vtuber = FakeVTuber()
    manager = OutputManager(bus, vtuber_provider=vtuber)
    manager.start()

    await bus.publish(ExpressionChange(name="happy", intensity=0.9))

    assert vtuber.expressions == [("happy", 0.9)]


@pytest.mark.asyncio
async def test_output_manager_no_vtuber_expression_does_not_raise():
    """ExpressionChange without a VTuber provider silently no-ops."""
    bus = EventBus()
    manager = OutputManager(bus)
    manager.start()

    # Should not raise
    await bus.publish(ExpressionChange(name="sad", intensity=0.5))


# ---------------------------------------------------------------------------
# OutputManager — start / stop subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_manager_stop_unsubscribes(capsys):
    """After stop(), OutputManager no longer responds to events."""
    bus = EventBus()
    tts = FakeTTS()
    manager = OutputManager(bus, tts_provider=tts, speech_output=False)
    manager.start()
    manager.stop()

    await bus.publish(LLMResponse(text="Should not print", expressions=[], actions=[], mood="neutral"))

    captured = capsys.readouterr()
    assert "Should not print" not in captured.out
    assert len(tts.synthesize_calls) == 0
