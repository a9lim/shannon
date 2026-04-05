"""Webcam capture provider using OpenCV."""

from __future__ import annotations

import asyncio

from shannon.vision.providers.base import VisionProvider


class WebcamCapture(VisionProvider):
    """Captures a frame from the default webcam as PNG bytes using OpenCV (lazy-loaded)."""

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index
        self._cap = None

    def _get_cap(self):
        if self._cap is None:
            import cv2
            self._cap = cv2.VideoCapture(self._device_index)
        return self._cap

    async def capture(self) -> bytes:
        """Read a frame from the webcam and return it as PNG bytes (non-blocking)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._capture_sync)

    def _capture_sync(self) -> bytes:
        """Synchronous capture implementation."""
        import cv2
        cap = self._get_cap()
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Failed to read frame from webcam")
        success, buf = cv2.imencode(".png", frame)
        if not success:
            raise RuntimeError("Failed to encode webcam frame as PNG")
        return buf.tobytes()

    def source_name(self) -> str:
        return "cam"

    async def close(self) -> None:
        """Release the underlying VideoCapture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
