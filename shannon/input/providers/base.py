"""Abstract base class for Speech-to-Text providers."""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str: ...

    @abstractmethod
    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]: ...
