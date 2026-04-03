"""Screen capture provider using mss."""

from __future__ import annotations

from shannon.vision.providers.base import VisionProvider


def _resize_image(png_bytes: bytes, max_width: int, max_height: int) -> bytes:
    """Resize a PNG image to fit within max_width x max_height, preserving aspect ratio.

    Returns original bytes if already within bounds.
    """
    import io
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes))
    if img.width <= max_width and img.height <= max_height:
        return png_bytes

    img.thumbnail((max_width, max_height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class ScreenCapture(VisionProvider):
    """Captures the primary monitor as PNG bytes using mss (lazy-loaded)."""

    def __init__(self, max_width: int = 1024, max_height: int = 768) -> None:
        self._mss = None
        self._max_width = max_width
        self._max_height = max_height

    def _get_mss(self):
        if self._mss is None:
            import mss
            self._mss = mss.mss()
        return self._mss

    async def capture(self) -> bytes:
        """Capture monitor[0] (the full virtual screen), resize, and return PNG bytes."""
        import mss.tools

        sct = self._get_mss()
        monitor = sct.monitors[0]
        screenshot = sct.grab(monitor)
        png_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)
        return _resize_image(png_bytes, self._max_width, self._max_height)

    def source_name(self) -> str:
        return "screen"
