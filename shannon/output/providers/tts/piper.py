"""PiperProvider — lazy-loads piper-tts and synthesizes speech."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, AsyncIterator

from shannon.output.providers.tts.base import AudioChunk, TTSProvider

if TYPE_CHECKING:
    pass


class PiperProvider(TTSProvider):
    """TTS provider backed by piper-tts (lazy-loaded)."""

    def __init__(self, model_path: str, config_path: str | None = None) -> None:
        self._model_path = model_path
        self._config_path = config_path
        self._voice: object | None = None  # piper.voice.PiperVoice, loaded lazily

    # ------------------------------------------------------------------
    # Lazy loader
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Import and initialise piper on first use."""
        if self._voice is not None:
            return
        try:
            from piper.voice import PiperVoice  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "piper-tts is not installed. "
                "Install it with: pip install piper-tts"
            ) from exc
        self._voice = PiperVoice.load(
            model_path=self._model_path,
            config_path=self._config_path,
        )

    # ------------------------------------------------------------------
    # TTSProvider interface
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> AudioChunk:
        """Synthesize the entire text and return a single AudioChunk."""
        self._load()
        assert self._voice is not None

        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> AudioChunk:
        """Synchronous synthesis — runs in thread pool."""
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._voice.synthesize(text, wf)  # type: ignore[attr-defined]

        buf.seek(0)
        data = buf.read()

        # Read sample_rate from the wave header
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()

        return AudioChunk(data=data, sample_rate=sample_rate, channels=channels)

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize text and yield AudioChunks one sentence at a time."""
        self._load()
        assert self._voice is not None

        import asyncio

        loop = asyncio.get_running_loop()

        try:
            chunks = await loop.run_in_executor(None, self._stream_sync, text)
            for chunk in chunks:
                yield chunk
        except AttributeError:
            chunk = await self.synthesize(text)
            yield chunk

    def _stream_sync(self, text: str) -> list[AudioChunk]:
        """Collect all stream chunks synchronously — runs in thread pool."""
        result = []
        for audio_bytes in self._voice.synthesize_stream_raw(text):  # type: ignore[attr-defined]
            if isinstance(audio_bytes, (bytes, bytearray)):
                raw = bytes(audio_bytes)
            else:
                raw = audio_bytes.tobytes()
            result.append(AudioChunk(
                data=raw,
                sample_rate=self._voice.config.sample_rate,  # type: ignore[attr-defined]
                channels=1,
            ))
        return result

    async def get_phonemes(self, text: str) -> list[str]:
        """Return phoneme strings for the given text using piper's phonemiser."""
        self._load()
        assert self._voice is not None

        try:
            phonemes: list[str] = self._voice.get_phonemes(text)  # type: ignore[attr-defined]
            return phonemes
        except AttributeError:
            # piper may not expose get_phonemes directly; return empty list
            return []
