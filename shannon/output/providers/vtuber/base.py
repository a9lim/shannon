"""Abstract base class for VTuber avatar providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class VTuberProvider(ABC):
    """Abstract interface for controlling a VTuber avatar."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the VTuber backend."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the VTuber backend."""
        ...

    @abstractmethod
    async def set_expression(self, name: str, intensity: float) -> None:
        """Activate a named expression at the given intensity (0.0–1.0)."""
        ...

    @abstractmethod
    async def start_speaking(self, phonemes: list[str] | None = None) -> None:
        """Trigger speaking / lip-sync animation, optionally using phoneme hints."""
        ...

    @abstractmethod
    async def stop_speaking(self) -> None:
        """Stop speaking / lip-sync animation."""
        ...

    @abstractmethod
    async def set_idle_animation(self, name: str) -> None:
        """Activate a named idle animation."""
        ...
