# tests/test_computer_executor.py
"""Tests for ComputerUseExecutor — dispatches computer_20251124 tool actions."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from shannon.config import ComputerUseConfig
from shannon.computer.executor import ComputerUseExecutor


def _config(**kwargs) -> ComputerUseConfig:
    defaults = dict(enabled=True, require_confirmation=False)
    defaults.update(kwargs)
    return ComputerUseConfig(**defaults)


def _make_executor(width: int = 1280, height: int = 800) -> ComputerUseExecutor:
    """Create an executor with mss patched to return deterministic screen dimensions."""
    mock_monitor = {"width": width, "height": height}
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_sct.monitors = [None, mock_monitor]
    with patch("mss.mss", return_value=mock_sct):
        return ComputerUseExecutor(_config(), display_width=width, display_height=height)


@pytest.fixture
def executor():
    return _make_executor(1280, 800)


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------


async def test_screenshot_returns_image_dict(executor):
    """screenshot action returns a properly structured image dict."""
    fake_b64 = "aGVsbG8="
    with patch.object(executor._capture, "capture_base64", return_value=fake_b64):
        result = await executor.execute({"action": "screenshot"})
    assert result["type"] == "image"
    assert result["source"]["type"] == "base64"
    assert result["source"]["media_type"] == "image/png"
    assert result["source"]["data"] == fake_b64


# ---------------------------------------------------------------------------
# left_click
# ---------------------------------------------------------------------------


async def test_left_click_calls_pyautogui_click(executor):
    """left_click action calls pyautogui.click with scaled coordinates."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        # scale_to_real is identity for 1280x800 (no downscaling needed)
        result = await executor.execute({"action": "left_click", "coordinate": [100, 200]})
    mock_pg.click.assert_called_once_with(100, 200)
    assert "clicked" in result.lower() or result == "OK"


# ---------------------------------------------------------------------------
# type
# ---------------------------------------------------------------------------


async def test_type_action_uses_write_not_typewrite(executor):
    """type action calls pyautogui.write (not typewrite) to support Unicode."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        result = await executor.execute({"action": "type", "text": "hello world"})
    mock_pg.write.assert_called_once_with("hello world", interval=0.02)
    mock_pg.typewrite.assert_not_called()
    assert result == "OK"


# ---------------------------------------------------------------------------
# key
# ---------------------------------------------------------------------------


async def test_key_calls_pyautogui_hotkey(executor):
    """key action calls pyautogui.hotkey with split key string."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        result = await executor.execute({"action": "key", "text": "ctrl+c"})
    mock_pg.hotkey.assert_called_once_with("ctrl", "c")
    assert result == "OK"


async def test_key_single_key_calls_hotkey(executor):
    """Single key (no +) is passed as a single hotkey argument."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        result = await executor.execute({"action": "key", "text": "Return"})
    mock_pg.hotkey.assert_called_once_with("Return")
    assert result == "OK"


# ---------------------------------------------------------------------------
# mouse_move
# ---------------------------------------------------------------------------


async def test_mouse_move_calls_pyautogui_moveTo(executor):
    """mouse_move action calls pyautogui.moveTo with scaled coordinates."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        result = await executor.execute({"action": "mouse_move", "coordinate": [300, 400]})
    mock_pg.moveTo.assert_called_once_with(300, 400)
    assert result == "OK"


# ---------------------------------------------------------------------------
# scroll
# ---------------------------------------------------------------------------


async def test_scroll_calls_pyautogui_scroll(executor):
    """scroll action calls pyautogui.scroll with the correct click count."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        result = await executor.execute({
            "action": "scroll",
            "coordinate": [500, 300],
            "direction": "up",
            "amount": 3,
        })
    mock_pg.moveTo.assert_called_once_with(500, 300)
    mock_pg.scroll.assert_called_once_with(3)
    assert result == "OK"


async def test_scroll_down_passes_negative_amount(executor):
    """scroll down passes a negative value to pyautogui.scroll."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        await executor.execute({
            "action": "scroll",
            "coordinate": [500, 300],
            "direction": "down",
            "amount": 2,
        })
    mock_pg.scroll.assert_called_once_with(-2)


# ---------------------------------------------------------------------------
# unknown action
# ---------------------------------------------------------------------------


async def test_unknown_action_returns_error(executor):
    """An unrecognised action returns a dict with an error message."""
    result = await executor.execute({"action": "fly_to_moon"})
    assert isinstance(result, dict) or isinstance(result, str)
    if isinstance(result, dict):
        assert "error" in result or "unknown" in str(result).lower()
    else:
        assert "unknown" in result.lower() or "unsupported" in result.lower()


# ---------------------------------------------------------------------------
# hold_key duration cap
# ---------------------------------------------------------------------------


async def test_hold_key_duration_capped(executor):
    """hold_key caps sleep duration at _MAX_DURATION (30s) regardless of LLM request."""
    import shannon.computer.executor as executor_mod
    slept = []
    with patch("shannon.computer.executor.pyautogui"):
        with patch("time.sleep", side_effect=lambda d: slept.append(d)):
            result = await executor.execute({"action": "hold_key", "text": "a", "duration": 99999})
    assert result == "OK"
    assert slept, "time.sleep was never called"
    assert max(slept) <= executor_mod._MAX_DURATION


# ---------------------------------------------------------------------------
# wait duration cap
# ---------------------------------------------------------------------------


async def test_wait_duration_capped(executor):
    """wait caps sleep duration at _MAX_DURATION (30s) regardless of LLM request."""
    import shannon.computer.executor as executor_mod
    slept = []
    with patch("shannon.computer.executor.pyautogui"):
        with patch("time.sleep", side_effect=lambda d: slept.append(d)):
            result = await executor.execute({"action": "wait", "duration": 99999})
    assert result == "OK"
    assert slept, "time.sleep was never called"
    assert max(slept) <= executor_mod._MAX_DURATION


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


def test_shutdown_calls_executor_shutdown(executor):
    """shutdown() delegates to the thread pool executor without raising."""
    with patch.object(executor._executor, "shutdown") as mock_shutdown:
        executor.shutdown()
    mock_shutdown.assert_called_once_with(wait=False)
