"""Screen capture provider using mss."""

from __future__ import annotations

from shannon.vision.providers.base import VisionProvider


class ScreenCapture(VisionProvider):
    """Captures the primary monitor as PNG bytes using mss (lazy-loaded)."""

    def __init__(self) -> None:
        self._mss = None

    def _get_mss(self):
        if self._mss is None:
            import mss
            self._mss = mss.mss()
        return self._mss

    async def capture(self) -> bytes:
        """Capture monitor[0] (the full virtual screen) and return PNG bytes."""
        import mss.tools

        sct = self._get_mss()
        monitor = sct.monitors[0]
        screenshot = sct.grab(monitor)
        return mss.tools.to_png(screenshot.rgb, screenshot.size)

    def source_name(self) -> str:
        return "screen"
