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


@pytest.fixture
def executor():
    return ComputerUseExecutor(_config(), display_width=1280, display_height=800)


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


async def test_type_calls_pyautogui_typewrite(executor):
    """type action calls pyautogui.typewrite with the given text."""
    with patch("shannon.computer.executor.pyautogui") as mock_pg:
        result = await executor.execute({"action": "type", "text": "hello world"})
    mock_pg.typewrite.assert_called_once_with("hello world", interval=0.02)
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
