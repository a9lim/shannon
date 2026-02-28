"""Tests for AutonomyLoop — idle timeout, screen change, cooldown, disabled."""

import asyncio
import pytest

from shannon.bus import EventBus
from shannon.config import AutonomyConfig, ShannonConfig
from shannon.events import AutonomousTrigger, UserInput, VisionFrame
from shannon.autonomy.loop import AutonomyLoop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(
    enabled: bool = True,
    cooldown_seconds: int = 0,
    triggers: list[str] | None = None,
    idle_timeout_seconds: int = 1,
) -> ShannonConfig:
    cfg = ShannonConfig()
    cfg.autonomy = AutonomyConfig(
        enabled=enabled,
        cooldown_seconds=cooldown_seconds,
        triggers=triggers if triggers is not None else ["idle_timeout", "screen_change"],
        idle_timeout_seconds=idle_timeout_seconds,
    )
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idle_timeout_triggers():
    """AutonomyLoop emits AutonomousTrigger(reason='idle_timeout') after idle period."""
    bus = EventBus()
    config = make_config(
        enabled=True,
        cooldown_seconds=0,
        triggers=["idle_timeout"],
        idle_timeout_seconds=0,  # trigger immediately — any idle time counts
    )
    loop = AutonomyLoop(bus, config)

    received: list[AutonomousTrigger] = []

    async def on_trigger(event: AutonomousTrigger):
        received.append(event)

    bus.subscribe(AutonomousTrigger, on_trigger)

    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.3)
    loop.stop()
    await task

    assert len(received) >= 1
    assert received[0].reason == "idle_timeout"


@pytest.mark.asyncio
async def test_screen_change_triggers():
    """AutonomyLoop emits AutonomousTrigger(reason='screen_change') when frame content changes."""
    bus = EventBus()
    config = make_config(
        enabled=True,
        cooldown_seconds=0,
        triggers=["screen_change"],
    )
    loop = AutonomyLoop(bus, config)

    received: list[AutonomousTrigger] = []

    async def on_trigger(event: AutonomousTrigger):
        received.append(event)

    bus.subscribe(AutonomousTrigger, on_trigger)

    task = asyncio.create_task(loop.run())
    # Yield to let the loop start and subscribe before publishing frames
    await asyncio.sleep(0.05)

    # Publish first frame — sets baseline hash, no trigger
    await bus.publish(VisionFrame(image=b"frame-one", source="screen"))
    await asyncio.sleep(0.15)

    # Publish second frame with different content — should trigger
    await bus.publish(VisionFrame(image=b"frame-two", source="screen"))
    await asyncio.sleep(0.15)

    loop.stop()
    await task

    assert len(received) >= 1
    assert received[0].reason == "screen_change"


@pytest.mark.asyncio
async def test_cooldown_respected():
    """Only one trigger fires when cooldown is longer than the test window."""
    bus = EventBus()
    config = make_config(
        enabled=True,
        cooldown_seconds=60,  # very long cooldown
        triggers=["idle_timeout"],
        idle_timeout_seconds=0,
    )
    loop = AutonomyLoop(bus, config)

    received: list[AutonomousTrigger] = []

    async def on_trigger(event: AutonomousTrigger):
        received.append(event)

    bus.subscribe(AutonomousTrigger, on_trigger)

    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.4)
    loop.stop()
    await task

    assert len(received) == 1


@pytest.mark.asyncio
async def test_disabled_does_nothing():
    """AutonomyLoop.run() returns immediately when autonomy.enabled is False."""
    bus = EventBus()
    config = make_config(enabled=False)
    loop = AutonomyLoop(bus, config)

    received: list[AutonomousTrigger] = []

    async def on_trigger(event: AutonomousTrigger):
        received.append(event)

    bus.subscribe(AutonomousTrigger, on_trigger)

    # run() should return immediately — use wait_for to guard against hang
    await asyncio.wait_for(loop.run(), timeout=1.0)

    assert len(received) == 0
