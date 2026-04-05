"""CoquiProvider — lazy-loads coqui-tts and synthesizes speech."""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

import numpy as np

from shannon.output.providers.tts.base import AudioChunk, TTSProvider

if TYPE_CHECKING:
    pass


class CoquiProvider(TTSProvider):
    """TTS provider backed by coqui-tts (lazy-loaded)."""

    def __init__(self, model_name: str, speaker: str = "") -> None:
        self._model_name = model_name
        self._speaker = speaker or None
        self._tts: object | None = None  # TTS.api.TTS, loaded lazily
        self._sample_rate: int = 22050  # updated after load

    # ------------------------------------------------------------------
    # Lazy loader
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Import and initialise coqui-tts on first use."""
        if self._tts is not None:
            return
        try:
            from TTS.api import TTS  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "coqui-tts is not installed. "
                "Install it with: pip install coqui-tts"
            ) from exc
        self._tts = TTS(model_name=self._model_name)
        self._sample_rate = self._tts.synthesizer.output_sample_rate  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # TTSProvider interface
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> AudioChunk:
        """Synthesize the entire text and return a single AudioChunk."""
        self._load()
        assert self._tts is not None

        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> AudioChunk:
        """Synchronous synthesis — runs in thread pool."""
        wav = self._tts.tts(text=text, speaker=self._speaker)  # type: ignore[attr-defined]
        audio = np.array(wav, dtype=np.float32)
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767).astype(np.int16)
        return AudioChunk(data=pcm.tobytes(), sample_rate=self._sample_rate, channels=1)

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize text and yield as a single AudioChunk (no streaming API)."""
        chunk = await self.synthesize(text)
        yield chunk

    async def get_phonemes(self, text: str) -> list[str]:
        """Return phoneme strings — not supported by coqui-tts."""
        return []
