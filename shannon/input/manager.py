"""InputManager — routes text and audio input to the event bus."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shannon.events import UserInput

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.input.providers.base import STTProvider
    from shannon.input.providers.text import TextInputProvider


class InputManager:
    def __init__(
        self,
        bus: "EventBus",
        text_provider: "TextInputProvider | None" = None,
        stt_provider: "STTProvider | None" = None,
    ) -> None:
        self._bus = bus
        self._text_provider = text_provider
        self._stt_provider = stt_provider
        self._speech_mode: bool = False

    async def handle_text(self, text: str) -> None:
        """Emit UserInput if text is non-empty after stripping."""
        stripped = text.strip()
        if not stripped:
            return
        await self._bus.publish(UserInput(text=stripped, source="text"))

    async def handle_audio(self, audio: bytes) -> None:
        """Transcribe via STT and emit UserInput with source='voice'."""
        if self._stt_provider is None:
            return
        transcription = await self._stt_provider.transcribe(audio)
        stripped = transcription.strip()
        if not stripped:
            return
        await self._bus.publish(UserInput(text=stripped, source="voice"))

    async def run_text_loop(self) -> None:
        """Loop reading lines from the text provider and forwarding them."""
        if self._text_provider is None:
            return
        while True:
            line = await self._text_provider.read_line()
            if line is None:
                break
            await self.handle_text(line)

    def set_speech_mode(self, enabled: bool) -> None:
        self._speech_mode = enabled
