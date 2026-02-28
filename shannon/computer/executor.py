# shannon/computer/executor.py
"""ComputerUseExecutor — executes Anthropic computer_20251124 tool actions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

try:
    import pyautogui
except ImportError:
    pyautogui = None  # type: ignore[assignment]

from shannon.config import ComputerUseConfig
from shannon.computer.screenshot import ScreenCapture


class ComputerUseExecutor:
    """Executes computer use actions dispatched from the computer_20251124 tool.

    Args:
        config: ComputerUseConfig from ShannonConfig.
        display_width: Logical display width presented to the LLM.
        display_height: Logical display height presented to the LLM.
    """

    def __init__(
        self,
        config: ComputerUseConfig,
        display_width: int = 1280,
        display_height: int = 800,
    ) -> None:
        self._config = config
        self._capture = ScreenCapture(display_width, display_height)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="computer_use")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, params: dict[str, Any]) -> Any:
        """Dispatch an action and return the result.

        Args:
            params: Dict with at least an ``action`` key.

        Returns:
            Either a dict (for screenshot) or a string status.
        """
        action = params.get("action")
        if action == "screenshot":
            return await self._screenshot()
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
        else:
            x = y = None

        # ---- click actions ----
        if action == "left_click":
            pyautogui.click(x, y)
            return "OK"

        if action == "right_click":
            pyautogui.rightClick(x, y)
            return "OK"

        if action == "middle_click":
            pyautogui.middleClick(x, y)
            return "OK"

        if action == "double_click":
            pyautogui.doubleClick(x, y)
            return "OK"

        if action == "triple_click":
            pyautogui.tripleClick(x, y)
            return "OK"

        # ---- keyboard ----
        if action == "type":
            text = params.get("text", "")
            pyautogui.typewrite(text, interval=0.02)
            return "OK"

        if action == "key":
            text = params.get("text", "")
            keys = text.split("+")
            pyautogui.hotkey(*keys)
            return "OK"

        # ---- mouse movement ----
        if action == "mouse_move":
            pyautogui.moveTo(x, y)
            return "OK"

        # ---- scroll ----
        if action == "scroll":
            direction = params.get("direction", "up")
            amount = int(params.get("amount", 1))
            pyautogui.moveTo(x, y)
            clicks = amount if direction == "up" else -amount
            pyautogui.scroll(clicks)
            return "OK"

        # ---- drag ----
        if action == "left_click_drag":
            end = params.get("endCoordinate") or params.get("end_coordinate")
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
            duration = float(params.get("duration", 1.0))
            pyautogui.keyDown(key)
            import time
            time.sleep(duration)
            pyautogui.keyUp(key)
            return "OK"

        # ---- wait ----
        if action == "wait":
            duration = float(params.get("duration", 1.0))
            import time
            time.sleep(duration)
            return "OK"

        return f"Error: unknown action '{action}'"
