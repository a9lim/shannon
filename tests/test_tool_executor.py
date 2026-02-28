"""Tests for the tool executor loop."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from shannon.core.auth import PermissionLevel
from shannon.core.llm.types import LLMMessage, LLMResponse, ToolCall
from shannon.core.tool_executor import ToolExecutor
from shannon.tools.base import BaseTool, ToolResult


class FakeTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes input"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.TRUSTED

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output=kwargs.get("text", ""))


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock()
    return llm


@pytest.fixture
def executor(mock_llm):
    tool = FakeTool()
    return ToolExecutor(mock_llm, {"echo": tool})


class TestToolExecutor:
    async def test_no_tool_calls_returns_content(self, executor, mock_llm):
        mock_llm.complete.return_value = LLMResponse(content="Hello!")
        result = await executor.run(
            [LLMMessage(role="user", content="Hi")],
            "system prompt",
            [],
            PermissionLevel.OPERATOR,
        )
        assert result == "Hello!"

    async def test_tool_call_executes_and_returns(self, executor, mock_llm):
        # First call returns a tool call
        mock_llm.complete.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tc1", name="echo", arguments={"text": "pong"})],
            ),
            LLMResponse(content="Done: pong"),
        ]
        result = await executor.run(
            [LLMMessage(role="user", content="ping")],
            "system prompt",
            [{"name": "echo", "description": "Echoes", "input_schema": {}}],
            PermissionLevel.OPERATOR,
        )
        assert result == "Done: pong"
        assert mock_llm.complete.call_count == 2

    async def test_unknown_tool_returns_error(self, executor, mock_llm):
        mock_llm.complete.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tc1", name="nonexistent", arguments={})],
            ),
            LLMResponse(content="Oops"),
        ]
        result = await executor.run(
            [LLMMessage(role="user", content="go")],
            "system prompt",
            [],
            PermissionLevel.OPERATOR,
        )
        assert result == "Oops"

    async def test_permission_denied(self, executor, mock_llm):
        # User is PUBLIC, tool requires TRUSTED
        mock_llm.complete.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="tc1", name="echo", arguments={"text": "x"})],
            ),
            LLMResponse(content="Permission issue noted"),
        ]
        result = await executor.run(
            [LLMMessage(role="user", content="go")],
            "system prompt",
            [{"name": "echo", "description": "Echoes", "input_schema": {}}],
            PermissionLevel.PUBLIC,
        )
        assert result == "Permission issue noted"
