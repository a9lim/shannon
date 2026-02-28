"""Tool-use loop: LLM calls with iterative tool execution."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMMessage, LLMProvider, LLMResponse
from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class ToolExecutor:
    """Runs the LLM completion + tool-use loop."""

    def __init__(self, llm: LLMProvider, tool_map: dict[str, BaseTool]) -> None:
        self._llm = llm
        self._tool_map = tool_map

    async def run(
        self,
        messages: list[LLMMessage],
        system: str,
        tool_schemas: list[dict[str, Any]],
        user_level: PermissionLevel,
        max_iterations: int = 10,
    ) -> str:
        """Run LLM completion with tool-use loop. Returns response text."""
        current_messages = list(messages)
        response: LLMResponse | None = None

        for _ in range(max_iterations):
            response = await self._llm.complete(
                messages=current_messages,
                system=system,
                tools=tool_schemas if tool_schemas else None,
            )

            # No tool calls — return the text
            if not response.tool_calls:
                return response.content

            # Process tool calls
            tool_results_content: list[dict[str, Any]] = []

            # Add assistant message with tool use
            assistant_content: list[dict[str, Any]] = []
            if response.content:
                assistant_content.append({"type": "text", "text": response.content})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            current_messages.append(LLMMessage(role="assistant", content=assistant_content))

            for tc in response.tool_calls:
                tool = self._tool_map.get(tc.name)
                if not tool:
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: Unknown tool '{tc.name}'",
                        "is_error": True,
                    })
                    continue

                # Permission check
                if user_level < tool.required_permission:
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": (
                            f"Permission denied. Tool '{tc.name}' requires "
                            f"{PermissionLevel(tool.required_permission).name} level."
                        ),
                        "is_error": True,
                    })
                    continue

                # Execute tool
                log.info("tool_executing", tool=tc.name, args=tc.arguments)
                result: ToolResult = await tool.execute(**tc.arguments)

                output = result.output if result.success else f"Error: {result.error}"
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": output,
                    "is_error": not result.success,
                })

            current_messages.append(LLMMessage(role="user", content=tool_results_content))

        return response.content if response else ""
