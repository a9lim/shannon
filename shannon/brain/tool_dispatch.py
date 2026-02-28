"""Tool dispatcher — routes LLM tool calls to the correct local executor."""

from __future__ import annotations

from typing import Any

from shannon.brain.types import LLMToolCall


_SERVER_SIDE_TOOLS = {"web_search", "web_fetch", "code_execution"}


class ToolDispatcher:
    """Routes tool_use blocks from Claude's response to the correct executor.

    Server-side tools (web_search, web_fetch, code_execution) don't need
    dispatch — results are already in the API response.

    Parameters
    ----------
    computer_executor:
        Executor for the ``computer`` tool (async ``execute(params) -> str | dict``).
    bash_executor:
        Executor for the ``bash`` tool (async ``execute(params) -> str``).
    text_editor_executor:
        Executor for the ``str_replace_based_edit_tool`` tool (sync ``execute(params) -> str``).
    memory_backend:
        Executor for the ``memory`` tool (sync ``execute(params) -> str``).
    """

    def __init__(
        self,
        computer_executor: Any = None,
        bash_executor: Any = None,
        text_editor_executor: Any = None,
        memory_backend: Any = None,
    ) -> None:
        self._computer = computer_executor
        self._bash = bash_executor
        self._text_editor = text_editor_executor
        self._memory = memory_backend

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, tool_call: LLMToolCall) -> str | dict:
        """Route a tool call to the appropriate executor and return its result."""
        name = tool_call.name
        args = tool_call.arguments

        if name == "continue":
            return "Continuing."

        if name == "set_expression":
            expr_name = args.get("name", "neutral")
            intensity = float(args.get("intensity", 0.7))
            return f"Expression set to {expr_name} (intensity {intensity})"

        if name == "bash":
            if self._bash is None:
                return "Error: bash executor is not available."
            return await self._bash.execute(args)

        if name == "str_replace_based_edit_tool":
            if self._text_editor is None:
                return "Error: text_editor executor is not available."
            return self._text_editor.execute(args)

        if name == "memory":
            if self._memory is None:
                return "Error: memory backend is not available."
            return self._memory.execute(args)

        if name == "computer":
            if self._computer is None:
                return "Error: computer executor is not available."
            return await self._computer.execute(args)

        return f"Unknown tool: {name}"

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_continue(name: str) -> bool:
        """Return True if the tool name is the ``continue`` signal."""
        return name == "continue"

    @staticmethod
    def is_expression(name: str) -> bool:
        """Return True if the tool name is ``set_expression``."""
        return name == "set_expression"

    @staticmethod
    def is_server_side(name: str) -> bool:
        """Return True if the tool is handled server-side (no local dispatch needed)."""
        return name in _SERVER_SIDE_TOOLS
