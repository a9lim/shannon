"""WhisperProvider — faster-whisper backed STT provider."""

import asyncio
import tempfile
import os
from typing import AsyncIterator

from shannon.input.providers.base import STTProvider


class WhisperProvider(STTProvider):
    """Speech-to-text using faster-whisper with lazy model loading."""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None

    def _get_model(self):
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def _transcribe_blocking(self, audio: bytes) -> str:
        """Run transcription synchronously (intended for executor use)."""
        model = self._get_model()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio)
            tmp_path = f.name
        try:
            segments, _ = model.transcribe(tmp_path)
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            os.unlink(tmp_path)

    async def transcribe(self, audio: bytes) -> str:
        """Transcribe audio bytes to text."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_blocking, audio)

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
        """Accumulate audio chunks then transcribe the full buffer."""
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            chunks.append(chunk)

        if not chunks:
            async def _empty():
                return
                yield  # make it an async generator
            return _empty()

        audio = b"".join(chunks)
        text = await self.transcribe(audio)

        async def _result():
            if text:
                yield text

        return _result()
