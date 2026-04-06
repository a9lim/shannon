"""Tests for ToolDispatcher — routes LLM tool calls to the correct executor."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from shannon.brain.types import LLMToolCall
from shannon.brain.tool_dispatch import ToolDispatcher
from shannon.bus import EventBus
from shannon.config import ToolsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_call(name: str, arguments: dict | None = None) -> LLMToolCall:
    return LLMToolCall(id="tc_test", name=name, arguments=arguments or {})


def _make_dispatcher(
    computer=None,
    bash=None,
    text_editor=None,
) -> ToolDispatcher:
    return ToolDispatcher(
        computer_executor=computer,
        bash_executor=bash,
        text_editor_executor=text_editor,
    )


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


async def test_dispatch_bash_routes_to_bash_executor():
    """bash tool is routed to bash_executor.execute."""
    bash = AsyncMock()
    bash.execute = AsyncMock(return_value="bash output")
    dispatcher = _make_dispatcher(bash=bash)

    result = await dispatcher.dispatch(_make_call("bash", {"command": "echo hi"}))

    bash.execute.assert_called_once_with({"command": "echo hi"})
    assert result == "bash output"


async def test_dispatch_text_editor_routes_to_text_editor_executor():
    """str_replace_based_edit_tool is routed to text_editor_executor.execute."""
    editor = MagicMock()
    editor.execute = MagicMock(return_value="edit result")
    dispatcher = _make_dispatcher(text_editor=editor)

    result = await dispatcher.dispatch(_make_call("str_replace_based_edit_tool", {"command": "view"}))

    editor.execute.assert_called_once_with({"command": "view"})
    assert result == "edit result"


def test_memory_is_not_server_side():
    assert ToolDispatcher.is_server_side("memory") is False


async def test_dispatch_memory_routes_to_memory_backend():
    """memory tool is routed to memory_backend.execute."""
    memory = MagicMock()
    memory.execute = MagicMock(return_value="File created successfully at: /memories/test.md")
    dispatcher = ToolDispatcher(memory_backend=memory)

    result = await dispatcher.dispatch(_make_call("memory", {"command": "create", "path": "/memories/test.md"}))

    memory.execute.assert_called_once_with({"command": "create", "path": "/memories/test.md"})
    assert "File created successfully" in result


async def test_dispatch_memory_missing_returns_error():
    """memory tool without backend returns error."""
    dispatcher = _make_dispatcher()

    result = await dispatcher.dispatch(_make_call("memory", {"command": "view"}))

    assert "not available" in result


async def test_dispatch_computer_routes_to_computer_executor():
    """computer tool is routed to computer_executor.execute."""
    computer = AsyncMock()
    computer.execute = AsyncMock(return_value={"type": "image"})
    dispatcher = _make_dispatcher(computer=computer)

    result = await dispatcher.dispatch(_make_call("computer", {"action": "screenshot"}))

    computer.execute.assert_called_once_with({"action": "screenshot"})
    assert result == {"type": "image"}


# ---------------------------------------------------------------------------
# set_expression
# ---------------------------------------------------------------------------


async def test_dispatch_set_expression_returns_ok():
    """set_expression returns 'ok'."""
    dispatcher = _make_dispatcher()

    result = await dispatcher.dispatch(_make_call("set_expression", {"name": "happy", "intensity": 0.8}))

    assert result == "ok"


# ---------------------------------------------------------------------------
# continue
# ---------------------------------------------------------------------------


async def test_dispatch_continue_returns_ok():
    """continue tool returns 'ok'."""
    dispatcher = _make_dispatcher()

    result = await dispatcher.dispatch(_make_call("continue"))

    assert result == "ok"


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


async def test_dispatch_unknown_tool_returns_error():
    """Unknown tool name returns an error string."""
    dispatcher = _make_dispatcher()

    result = await dispatcher.dispatch(_make_call("nonexistent_tool_xyz"))

    assert "Unknown tool" in result
    assert "nonexistent_tool_xyz" in result


# ---------------------------------------------------------------------------
# None executor errors
# ---------------------------------------------------------------------------


async def test_dispatch_bash_with_none_executor_returns_error():
    """If bash_executor is None, dispatch returns an error string."""
    dispatcher = _make_dispatcher(bash=None)

    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))

    assert isinstance(result, str)
    assert "bash" in result.lower() or "not" in result.lower() or "unavailable" in result.lower() or "error" in result.lower()


async def test_dispatch_computer_with_none_executor_returns_error():
    """If computer_executor is None, dispatch returns an error string."""
    dispatcher = _make_dispatcher(computer=None)

    result = await dispatcher.dispatch(_make_call("computer", {"action": "screenshot"}))

    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Static helper methods
# ---------------------------------------------------------------------------


def test_is_continue_true():
    assert ToolDispatcher.is_continue("continue") is True


def test_is_continue_false():
    assert ToolDispatcher.is_continue("bash") is False


def test_is_expression_true():
    assert ToolDispatcher.is_expression("set_expression") is True


def test_is_expression_false():
    assert ToolDispatcher.is_expression("memory") is False


def test_is_server_side_true():
    assert ToolDispatcher.is_server_side("web_search") is True
    assert ToolDispatcher.is_server_side("web_fetch") is True
    assert ToolDispatcher.is_server_side("code_execution") is True


def test_is_server_side_false():
    assert ToolDispatcher.is_server_side("bash") is False
    assert ToolDispatcher.is_server_side("computer") is False
    assert ToolDispatcher.is_server_side("set_expression") is False


# ---------------------------------------------------------------------------
# Confirmation gate tests
# ---------------------------------------------------------------------------


async def test_dispatch_bash_denied_when_confirmation_required(monkeypatch):
    """When require_confirmation=True and no handler approves, dispatch returns denial."""
    import shannon.brain.tool_dispatch as td
    monkeypatch.setattr(td, "_CONFIRMATION_TIMEOUT", 0.1)

    bus = EventBus()
    config = ToolsConfig()
    dispatcher = ToolDispatcher(
        bash_executor=AsyncMock(execute=AsyncMock(return_value="output")),
        tools_config=config,
        bus=bus,
    )
    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))
    assert "denied" in result.lower()


async def test_dispatch_bash_allowed_when_confirmation_false():
    """When require_confirmation=False, dispatch executes without confirmation."""
    bus = EventBus()
    config = ToolsConfig()
    config.bash.require_confirmation = False
    bash = AsyncMock(execute=AsyncMock(return_value="output"))
    dispatcher = ToolDispatcher(
        bash_executor=bash,
        tools_config=config,
        bus=bus,
    )
    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))
    assert result == "output"
    bash.execute.assert_called_once()


async def test_dispatch_bash_approved_via_bus():
    """When a handler approves via ToolConfirmationResponse, dispatch proceeds."""
    from shannon.events import ToolConfirmationRequest, ToolConfirmationResponse

    bus = EventBus()
    config = ToolsConfig()
    bash = AsyncMock(execute=AsyncMock(return_value="output"))
    dispatcher = ToolDispatcher(
        bash_executor=bash,
        tools_config=config,
        bus=bus,
    )

    async def auto_approve(event: ToolConfirmationRequest) -> None:
        await bus.publish(ToolConfirmationResponse(
            request_id=event.request_id, approved=True,
        ))

    bus.subscribe(ToolConfirmationRequest, auto_approve)

    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))
    assert result == "output"
