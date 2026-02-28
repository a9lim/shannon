"""Tests for the vision system: providers and VisionManager."""

import asyncio
import pytest

from shannon.bus import EventBus
from shannon.events import VisionFrame
from shannon.vision.providers.base import VisionProvider
from shannon.vision.manager import VisionManager


# ---------------------------------------------------------------------------
# Fake providers for testing
# ---------------------------------------------------------------------------

class FakeScreenCapture(VisionProvider):
    """Fake screen capture that returns synthetic PNG bytes."""

    async def capture(self) -> bytes:
        return b"fake-screen-png"

    def source_name(self) -> str:
        return "screen"


class FakeWebcamCapture(VisionProvider):
    """Fake webcam capture that returns synthetic PNG bytes."""

    async def capture(self) -> bytes:
        return b"fake-cam-png"

    def source_name(self) -> str:
        return "cam"


# ---------------------------------------------------------------------------
# VisionProvider ABC tests
# ---------------------------------------------------------------------------

def test_vision_provider_is_abstract():
    """VisionProvider cannot be instantiated directly."""
    try:
        VisionProvider()
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


def test_vision_provider_requires_capture():
    """A subclass missing capture() cannot be instantiated."""

    class IncompleteProvider(VisionProvider):
        def source_name(self) -> str:
            return "screen"

    try:
        IncompleteProvider()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_vision_provider_requires_source_name():
    """A subclass missing source_name() cannot be instantiated."""

    class IncompleteProvider(VisionProvider):
        async def capture(self) -> bytes:
            return b""

    try:
        IncompleteProvider()
        assert False, "Should not instantiate with missing abstract method"
    except TypeError:
        pass


def test_vision_provider_concrete_subclass_instantiates():
    """A complete concrete subclass of VisionProvider can be instantiated."""
    provider = FakeScreenCapture()
    assert isinstance(provider, VisionProvider)
    assert provider.source_name() == "screen"


# ---------------------------------------------------------------------------
# VisionManager — single source tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_source_emits_vision_frame_events():
    """A single provider should emit VisionFrame events at the given interval."""
    bus = EventBus()
    provider = FakeScreenCapture()
    manager = VisionManager(bus, providers=[provider], interval_seconds=0.05)

    received: list[VisionFrame] = []

    async def capture(event: VisionFrame):
        received.append(event)

    bus.subscribe(VisionFrame, capture)

    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.15)
    manager.stop()
    await task

    assert len(received) >= 2
    for event in received:
        assert event.source == "screen"
        assert event.image == b"fake-screen-png"


@pytest.mark.asyncio
async def test_single_source_emits_correct_image_bytes():
    """VisionFrame events should carry the bytes returned by capture()."""
    bus = EventBus()
    provider = FakeWebcamCapture()
    manager = VisionManager(bus, providers=[provider], interval_seconds=0.05)

    received: list[VisionFrame] = []

    async def capture(event: VisionFrame):
        received.append(event)

    bus.subscribe(VisionFrame, capture)

    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.15)
    manager.stop()
    await task

    assert len(received) >= 2
    assert all(e.image == b"fake-cam-png" for e in received)


# ---------------------------------------------------------------------------
# VisionManager — multiple sources tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_sources_emit_frames_with_different_source_names():
    """Multiple providers emit frames with distinct source names."""
    bus = EventBus()
    screen = FakeScreenCapture()
    cam = FakeWebcamCapture()
    manager = VisionManager(bus, providers=[screen, cam], interval_seconds=0.05)

    received: list[VisionFrame] = []

    async def capture(event: VisionFrame):
        received.append(event)

    bus.subscribe(VisionFrame, capture)

    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.15)
    manager.stop()
    await task

    sources = {e.source for e in received}
    assert "screen" in sources
    assert "cam" in sources


@pytest.mark.asyncio
async def test_multiple_sources_each_emit_multiple_frames():
    """Both providers should emit at least 2 frames each over the test window."""
    bus = EventBus()
    screen = FakeScreenCapture()
    cam = FakeWebcamCapture()
    manager = VisionManager(bus, providers=[screen, cam], interval_seconds=0.05)

    screen_frames: list[VisionFrame] = []
    cam_frames: list[VisionFrame] = []

    async def capture(event: VisionFrame):
        if event.source == "screen":
            screen_frames.append(event)
        else:
            cam_frames.append(event)

    bus.subscribe(VisionFrame, capture)

    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.15)
    manager.stop()
    await task

    assert len(screen_frames) >= 2
    assert len(cam_frames) >= 2


# ---------------------------------------------------------------------------
# VisionManager — stop behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_stops_emitting_after_stop():
    """No new frames should be emitted after stop() is called."""
    bus = EventBus()
    provider = FakeScreenCapture()
    manager = VisionManager(bus, providers=[provider], interval_seconds=0.05)

    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.15)
    manager.stop()
    await task

    # Count frames up to stop
    received_before: list[VisionFrame] = []

    async def capture(event: VisionFrame):
        received_before.append(event)

    bus.subscribe(VisionFrame, capture)

    # No more frames should arrive after stop
    await asyncio.sleep(0.1)
    assert len(received_before) == 0


@pytest.mark.asyncio
async def test_manager_run_returns_after_stop():
    """manager.run() coroutine should complete after stop() is called."""
    bus = EventBus()
    provider = FakeScreenCapture()
    manager = VisionManager(bus, providers=[provider], interval_seconds=0.05)

    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.08)
    manager.stop()
    # Should complete without hanging
    await asyncio.wait_for(task, timeout=1.0)


# ---------------------------------------------------------------------------
# VisionFrame event shape
# ---------------------------------------------------------------------------

def test_vision_frame_has_timestamp():
    """VisionFrame should automatically set a timestamp."""
    frame = VisionFrame(image=b"data", source="screen")
    assert frame.timestamp > 0


def test_vision_frame_fields():
    """VisionFrame should store image bytes and source name."""
    frame = VisionFrame(image=b"png-data", source="cam")
    assert frame.image == b"png-data"
    assert frame.source == "cam"
