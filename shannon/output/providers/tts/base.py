"""Abstract base class and data types for Text-to-Speech providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class AudioChunk:
    """A chunk of synthesized audio."""

    data: bytes
    sample_rate: int
    channels: int = 1


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @abstractmethod
    async def synthesize(self, text: str) -> AudioChunk:
        """Synthesize text into a single AudioChunk."""
        ...

    @abstractmethod
    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize text and yield AudioChunks as they become available."""
        ...

    @abstractmethod
    async def get_phonemes(self, text: str) -> list[str]:
        """Return a list of phoneme strings for the given text."""
        ...
