"""VisionManager — periodic capture loop that emits VisionFrame events."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from shannon.events import VisionFrame

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.vision.providers.base import VisionProvider


class VisionManager:
    """Periodically captures frames from all providers and emits VisionFrame events."""

    def __init__(
        self,
        bus: "EventBus",
        providers: "list[VisionProvider]",
        interval_seconds: float = 1.0,
    ) -> None:
        self._bus = bus
        self._providers = providers
        self._interval = interval_seconds
        self._running = False

    async def run(self) -> None:
        """Start the periodic capture loop. Runs until stop() is called."""
        self._running = True
        while self._running:
            for provider in self._providers:
                try:
                    image = await provider.capture()
                    await self._bus.publish(
                        VisionFrame(image=image, source=provider.source_name())
                    )
                except Exception:
                    pass
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        """Signal the capture loop to stop after the current iteration."""
        self._running = False
