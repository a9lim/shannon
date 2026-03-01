"""Pause/resume manager for autonomous behaviors."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from shannon.utils.logging import get_logger

log = get_logger(__name__)

_DURATION_RE = re.compile(
    r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE
)


def parse_duration(text: str) -> int | None:
    """Parse duration string like '2h', '30m', '1h30m'. Returns seconds or None."""
    if not text:
        return None
    m = _DURATION_RE.match(text.strip())
    if not m or not any(m.groups()):
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class PauseManager:
    def __init__(self) -> None:
        self._paused = False
        self._queued_events: list[dict[str, Any]] = []
        self._resume_task: asyncio.Task[None] | None = None

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def queued_events(self) -> list[dict[str, Any]]:
        return self._queued_events

    def pause(self, duration_seconds: float | None = None) -> None:
        self._paused = True
        log.info("shannon_paused", duration=duration_seconds)

        if duration_seconds is not None and duration_seconds > 0:
            loop = asyncio.get_event_loop()
            self._resume_task = loop.create_task(
                self._auto_resume(duration_seconds)
            )

    def resume(self) -> int:
        """Resume and return count of queued events."""
        if self._resume_task and not self._resume_task.done():
            self._resume_task.cancel()
            self._resume_task = None

        self._paused = False
        count = len(self._queued_events)
        log.info("shannon_resumed", queued_events=count)
        return count

    def drain_queue(self) -> list[dict[str, Any]]:
        events = list(self._queued_events)
        self._queued_events.clear()
        return events

    def queue_event(self, event: dict[str, Any]) -> None:
        self._queued_events.append(event)

    async def _auto_resume(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        self.resume()
        log.info("shannon_auto_resumed")
