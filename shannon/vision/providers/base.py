"""Abstract base class for vision capture providers."""

from abc import ABC, abstractmethod


class VisionProvider(ABC):
    @abstractmethod
    async def capture(self) -> bytes:
        """Capture an image and return it as PNG bytes."""
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier: 'screen' or 'cam'."""
        ...
