"""Tool dispatcher — routes LLM tool calls to the correct local executor."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from shannon.brain.types import LLMToolCall

_log = logging.getLogger(__name__)

_SERVER_SIDE_TOOLS = {"web_search", "web_fetch", "code_execution", "memory"}

_CONFIRMATION_TIMEOUT = 120


class ToolDispatcher:
    """Routes tool_use blocks from Claude's response to the correct executor.

    Server-side tools (web_search, web_fetch, code_execution, memory) don't need
    dispatch — results are already in the API response.

    Parameters
    ----------
    computer_executor:
        Executor for the ``computer`` tool (async ``execute(params) -> str | dict``).
    bash_executor:
        Executor for the ``bash`` tool (async ``execute(params) -> str``).
    text_editor_executor:
        Executor for the ``str_replace_based_edit_tool`` tool (sync ``execute(params) -> str``).
    tools_config:
        Optional ``ToolsConfig`` — when provided, ``require_confirmation`` flags
        are checked before executing gated tools.
    bus:
        Optional ``EventBus`` — when provided (together with *tools_config*),
        confirmation requests are published and responses awaited.
    """

    def __init__(
        self,
        computer_executor: Any = None,
        bash_executor: Any = None,
        text_editor_executor: Any = None,
        tools_config: Any = None,
        bus: Any = None,
    ) -> None:
        self._computer = computer_executor
        self._bash = bash_executor
        self._text_editor = text_editor_executor
        self._tools_config = tools_config
        self._bus = bus
        self.channel_id: str = ""
        self.participants: dict[str, str] = {}
        self._pending_confirmations: dict[str, asyncio.Future[bool]] = {}

        if bus is not None:
            from shannon.events import ToolConfirmationResponse
            bus.subscribe(ToolConfirmationResponse, self._on_confirmation_response)

    def set_context(self, channel_id: str, participants: dict[str, str]) -> None:
        """Update the conversation context for the current turn."""
        self.channel_id = channel_id
        self.participants = dict(participants)

    # ------------------------------------------------------------------
    # Confirmation helpers
    # ------------------------------------------------------------------

    def _needs_confirmation(self, name: str) -> bool:
        """Return True if the tool requires user confirmation before execution."""
        if self._tools_config is None or self._bus is None:
            return False
        if name == "bash":
            return self._tools_config.bash.require_confirmation
        if name == "str_replace_based_edit_tool":
            return self._tools_config.text_editor.require_confirmation
        if name == "computer":
            return self._tools_config.computer_use.require_confirmation
        return False

    @staticmethod
    def _describe_tool_call(name: str, args: dict) -> str:
        """Produce a human-readable summary of a tool call."""
        if name == "bash":
            cmd = args.get("command", "")
            return f"Run bash command: {cmd}"
        if name == "str_replace_based_edit_tool":
            command = args.get("command", "")
            path = args.get("path", "")
            return f"Text editor {command} on {path}"
        if name == "computer":
            action = args.get("action", "")
            return f"Computer action: {action}"
        return f"Execute tool: {name}"

    async def _request_confirmation(self, name: str, args: dict) -> bool:
        """Publish a confirmation request and wait for a response."""
        from shannon.events import ToolConfirmationRequest

        request_id = uuid.uuid4().hex
        description = self._describe_tool_call(name, args)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending_confirmations[request_id] = future

        await self._bus.publish(ToolConfirmationRequest(
            tool_name=name,
            description=description,
            request_id=request_id,
        ))

        try:
            return await asyncio.wait_for(future, timeout=_CONFIRMATION_TIMEOUT)
        except asyncio.TimeoutError:
            _log.warning("Confirmation timed out for %s (request %s)", name, request_id)
            return False
        finally:
            self._pending_confirmations.pop(request_id, None)

    async def _on_confirmation_response(self, event: Any) -> None:
        """Resolve a pending confirmation future when a response arrives."""
        future = self._pending_confirmations.get(event.request_id)
        if future is not None and not future.done():
            future.set_result(event.approved)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, tool_call: LLMToolCall) -> str | dict:
        """Route a tool call to the appropriate executor and return its result."""
        name = tool_call.name
        args = tool_call.arguments

        if name == "continue":
            return "ok"

        if name == "set_expression":
            _log.info("Expression → %s (%.1f)", args.get("name", "?"), args.get("intensity", 0))
            return "ok"

        # Confirmation gate for client-side gated tools
        if self._needs_confirmation(name):
            _log.info("Awaiting user confirmation for %s", name)
            approved = await self._request_confirmation(name, args)
            if not approved:
                _log.info("User denied %s", name)
                return f"Tool execution denied by user: {name}"
            _log.info("User approved %s", name)

        if name == "bash":
            if self._bash is None:
                return "Error: bash executor is not available."
            _log.info("Executing bash: %s", args.get("command", "")[:120])
            return await self._bash.execute(args)

        if name == "str_replace_based_edit_tool":
            if self._text_editor is None:
                return "Error: text_editor executor is not available."
            _log.info("Text editor %s on %s", args.get("command", "?"), args.get("path", "?"))
            return await asyncio.to_thread(self._text_editor.execute, args)

        if name == "computer":
            if self._computer is None:
                return "Error: computer executor is not available."
            _log.info("Computer action: %s", args.get("action", "?"))
            return await self._computer.execute(args)

        _log.warning("Unknown tool: %s", name)
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
