"""Autonomy loop — decides when Shannon should react unprompted."""

import asyncio
import hashlib
import time

from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import AutonomousTrigger, UserInput, VisionFrame


class AutonomyLoop:
    """Background loop that emits AutonomousTrigger when conditions are met."""

    def __init__(self, bus: EventBus, config: ShannonConfig) -> None:
        self._bus = bus
        self._config = config
        self._running = False
        self._last_trigger_times: dict[str, float] = {}
        self._last_input_time = time.time()
        self._last_frame_hash = ""
        self._latest_frame: VisionFrame | None = None
        self._last_checked_frame: VisionFrame | None = None

    async def run(self) -> None:
        """Start the autonomy loop. Returns immediately if autonomy is disabled."""
        if not self._config.autonomy.enabled:
            return
        self._running = True
        self._bus.subscribe(VisionFrame, self._on_vision_frame)
        self._bus.subscribe(UserInput, self._on_user_input)
        while self._running:
            await self._evaluate()
            await asyncio.sleep(1.0)

    def stop(self) -> None:
        """Stop the autonomy loop."""
        self._running = False
        self._bus.unsubscribe(VisionFrame, self._on_vision_frame)
        self._bus.unsubscribe(UserInput, self._on_user_input)

    async def _on_vision_frame(self, event: VisionFrame) -> None:
        self._latest_frame = event

    async def _on_user_input(self, event: UserInput) -> None:
        self._last_input_time = time.time()

    async def _evaluate(self) -> None:
        """Check trigger conditions and emit AutonomousTrigger if warranted."""
        now = time.time()
        cfg = self._config.autonomy
        cooldown = cfg.cooldown_seconds
        triggers = cfg.triggers

        # Check idle_timeout trigger (per-trigger cooldown)
        if "idle_timeout" in triggers:
            if now - self._last_trigger_times.get("idle_timeout", 0.0) >= cooldown:
                idle_seconds = now - self._last_input_time
                if idle_seconds >= cfg.idle_timeout_seconds:
                    self._last_trigger_times["idle_timeout"] = now
                    self._last_input_time = now  # reset so we don't fire again immediately
                    await self._bus.publish(AutonomousTrigger(
                        reason="idle_timeout",
                        context=f"No user input for {idle_seconds:.1f}s",
                    ))
                    return

        # Check screen_change trigger (per-trigger cooldown)
        if "screen_change" in triggers and self._latest_frame is not None:
            if now - self._last_trigger_times.get("screen_change", 0.0) >= cooldown:
                if self._latest_frame is not self._last_checked_frame:
                    self._last_checked_frame = self._latest_frame
                    frame_hash = hashlib.md5(self._latest_frame.image).hexdigest()
                    if frame_hash != self._last_frame_hash and self._last_frame_hash != "":
                        self._last_trigger_times["screen_change"] = now
                        self._last_frame_hash = frame_hash
                        await self._bus.publish(AutonomousTrigger(
                            reason="screen_change",
                            context=f"Screen content changed (hash: {frame_hash[:8]})",
                        ))
                        return
                    self._last_frame_hash = frame_hash
