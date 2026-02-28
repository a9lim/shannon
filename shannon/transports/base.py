"""Abstract transport base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from shannon.core.bus import EventBus


class Transport(ABC):
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    @property
    @abstractmethod
    def platform_name(self) -> str: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        reply_to: str | None = None,
        embed: dict | None = None,
        files: list[str] | None = None,
    ) -> None: ...
