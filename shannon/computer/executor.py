# shannon/computer/executor.py
"""ComputerUseExecutor — executes Anthropic computer_20251124 tool actions."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore[assignment]

from shannon.config import ComputerUseConfig
from shannon.computer.screenshot import ScreenCapture

_MAX_DURATION = 30.0  # seconds — cap for hold_key and wait actions


class ComputerUseExecutor:
    """Executes computer use actions dispatched from the computer_20251124 tool.

    Args:
        config: ComputerUseConfig from ShannonConfig.
        display_width: Logical display width presented to the LLM (fallback if detection fails).
        display_height: Logical display height presented to the LLM (fallback if detection fails).
    """

    def __init__(
        self,
        config: ComputerUseConfig,
        display_width: int = 1280,
        display_height: int = 800,
    ) -> None:
        self._config = config
        actual_width, actual_height = display_width, display_height
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                actual_width = monitor["width"]
                actual_height = monitor["height"]
        except Exception:
            pass
        self._capture = ScreenCapture(actual_width, actual_height)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="computer_use")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, params: dict[str, Any]) -> Any:
        """Dispatch an action and return the result.

        Args:
            params: Dict with at least an ``action`` key.

        Returns:
            Either a dict (for screenshot/zoom) or a string status.
        """
        action = params.get("action")
        if action == "screenshot":
            return await self._screenshot()
        if action == "zoom":
            return await self._zoom(params.get("region"))
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self._execute_sync, action, params
        )

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    async def _screenshot(self) -> dict:
        """Capture the screen and return an image content block."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(self._executor, self._capture.capture_base64)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": data,
            },
        }

    # ------------------------------------------------------------------
    # Zoom (region capture at full resolution)
    # ------------------------------------------------------------------

    async def _zoom(self, region: list | None) -> dict | str:
        """Capture a region of the screen at full resolution.

        Args:
            region: [x1, y1, x2, y2] in Claude's scaled coordinate space,
                    defining top-left and bottom-right corners.
        """
        if not region or len(region) != 4:
            return "Error: zoom requires a 'region' parameter with [x1, y1, x2, y2]"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._zoom_sync, region)

    def _zoom_sync(self, region: list) -> dict | str:
        """Capture a screen region at full resolution (runs in thread pool)."""
        try:
            import mss
            from PIL import Image
        except ImportError:
            return "Error: zoom requires mss and Pillow: pip install mss Pillow"

        # Scale from Claude's coordinate space to real screen coordinates
        x1, y1 = self._capture.scale_to_real(int(region[0]), int(region[1]))
        x2, y2 = self._capture.scale_to_real(int(region[2]), int(region[3]))

        # Ensure valid bounds
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        if x2 - x1 < 1 or y2 - y1 < 1:
            return "Error: zoom region is too small"

        with mss.mss() as sct:
            monitor = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        import base64
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": data,
            },
        }

    # ------------------------------------------------------------------
    # Synchronous action dispatch (run in thread executor)
    # ------------------------------------------------------------------

    def _execute_sync(self, action: str | None, params: dict[str, Any]) -> str:
        """Run a pyautogui action synchronously in a thread pool worker."""
        if pyautogui is None:
            return "Error: pyautogui is not installed"

        if action is None:
            return "Error: missing 'action' field"

        coord = params.get("coordinate")
        if coord is not None:
            x, y = self._capture.scale_to_real(int(coord[0]), int(coord[1]))
            if x < 0 or y < 0 or x > self._capture.real_width or y > self._capture.real_height:
                logger.warning(
                    "Coordinate (%d, %d) is outside display bounds (%dx%d)",
                    x, y, self._capture.real_width, self._capture.real_height,
                )
        else:
            x = y = None

        # ---- click actions ----
        # Click/scroll actions support modifier keys via the "text" param
        # (e.g. "shift", "ctrl", "alt", "super" for shift+click, ctrl+click, etc.)
        if action in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
            modifier = params.get("text")
            if modifier:
                pyautogui.keyDown(modifier)
            try:
                if action == "left_click":
                    pyautogui.click(x, y)
                elif action == "right_click":
                    pyautogui.rightClick(x, y)
                elif action == "middle_click":
                    pyautogui.middleClick(x, y)
                elif action == "double_click":
                    pyautogui.doubleClick(x, y)
                elif action == "triple_click":
                    pyautogui.tripleClick(x, y)
            finally:
                if modifier:
                    pyautogui.keyUp(modifier)
            return "OK"

        # ---- keyboard ----
        if action == "type":
            text = params.get("text", "")
            pyautogui.write(text, interval=0.02)
            return "OK"

        if action == "key":
            text = params.get("text", "")
            if not text:
                return "Error: key action requires 'text' parameter"
            keys = text.split("+")
            pyautogui.hotkey(*keys)
            return "OK"

        # ---- mouse movement ----
        if action == "mouse_move":
            pyautogui.moveTo(x, y)
            return "OK"

        # ---- scroll ----
        if action == "scroll":
            # Spec uses scroll_direction/scroll_amount; accept both for robustness
            direction = params.get("scroll_direction") or params.get("direction", "up")
            amount = int(params.get("scroll_amount") or params.get("amount", 1))
            modifier = params.get("text")
            if modifier:
                pyautogui.keyDown(modifier)
            try:
                pyautogui.moveTo(x, y)
                if direction in ("left", "right"):
                    clicks = amount if direction == "right" else -amount
                    pyautogui.hscroll(clicks)
                else:
                    clicks = amount if direction == "up" else -amount
                    pyautogui.scroll(clicks)
            finally:
                if modifier:
                    pyautogui.keyUp(modifier)
            return "OK"

        # ---- drag ----
        if action == "left_click_drag":
            end = params.get("end_coordinate")
            if end is not None:
                ex, ey = self._capture.scale_to_real(int(end[0]), int(end[1]))
            else:
                ex, ey = x, y
            pyautogui.mouseDown(x, y, button="left")
            pyautogui.moveTo(ex, ey)
            pyautogui.mouseUp(button="left")
            return "OK"

        # ---- mouse button down/up ----
        if action == "left_mouse_down":
            pyautogui.mouseDown(x, y, button="left")
            return "OK"

        if action == "left_mouse_up":
            pyautogui.mouseUp(x, y, button="left")
            return "OK"

        # ---- hold key ----
        if action == "hold_key":
            key = params.get("text", "")
            duration = min(float(params.get("duration", 1.0)), _MAX_DURATION)
            pyautogui.keyDown(key)
            import time
            time.sleep(duration)
            pyautogui.keyUp(key)
            return "OK"

        # ---- wait ----
        if action == "wait":
            duration = min(float(params.get("duration", 1.0)), _MAX_DURATION)
            import time
            time.sleep(duration)
            return "OK"

        return f"Error: unknown action '{action}'"

    def shutdown(self) -> None:
        """Shut down the thread pool executor."""
        self._executor.shutdown(wait=False)
