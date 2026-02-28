"""Screen capture module with resolution scaling for computer use.

Scales screenshots to satisfy Anthropic API limits:
- Max 1568px on the longest edge
- Max ~1.15 megapixels total
"""
import base64
import io
import math


class ScreenCapture:
    """Captures screenshots and scales them to fit Anthropic API constraints."""

    MAX_LONG_EDGE = 1568
    MAX_PIXELS = 1_150_000

    def __init__(self, real_width: int, real_height: int) -> None:
        self.real_width = real_width
        self.real_height = real_height
        self._scale = self._compute_scale()

    def _compute_scale(self) -> float:
        """Compute the scale factor needed to satisfy API constraints.

        Returns min(1.0, 1568/long_edge, sqrt(1_150_000/total_pixels)).
        """
        long_edge = max(self.real_width, self.real_height)
        total_pixels = self.real_width * self.real_height

        scale_long_edge = self.MAX_LONG_EDGE / long_edge
        scale_pixels = math.sqrt(self.MAX_PIXELS / total_pixels)

        return min(1.0, scale_long_edge, scale_pixels)

    @property
    def scaled_width(self) -> int:
        """Width after applying the scale factor."""
        return round(self.real_width * self._scale)

    @property
    def scaled_height(self) -> int:
        """Height after applying the scale factor."""
        return round(self.real_height * self._scale)

    def scale_to_real(self, x: float, y: float) -> tuple[int, int]:
        """Map coordinates from Claude's scaled space back to real screen space."""
        return round(x / self._scale), round(y / self._scale)

    def capture(self) -> bytes:
        """Capture the screen and return scaled PNG bytes.

        Requires mss and Pillow to be installed.
        """
        try:
            import mss
            from PIL import Image
        except ImportError as e:
            raise ImportError(
                "Screen capture requires mss and Pillow: pip install mss Pillow"
            ) from e

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        if self._scale < 1.0:
            new_size = (self.scaled_width, self.scaled_height)
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def capture_base64(self) -> str:
        """Capture the screen and return a base64-encoded PNG string."""
        return base64.b64encode(self.capture()).decode("ascii")
