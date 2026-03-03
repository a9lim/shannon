"""Tool-use loop: LLM calls with iterative tool execution."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMMessage, LLMProvider, LLMResponse, ToolCallResult
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

            # Add assistant message with tool calls
            current_messages.append(LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))

            # Execute tools and collect results
            results: list[ToolCallResult] = []
            for tc in response.tool_calls:
                tool = self._tool_map.get(tc.name)
                if not tool:
                    results.append(ToolCallResult(
                        id=tc.id,
                        output=f"Error: Unknown tool '{tc.name}'",
                        is_error=True,
                    ))
                    continue

                if user_level < tool.required_permission:
                    results.append(ToolCallResult(
                        id=tc.id,
                        output=(
                            f"Permission denied. Tool '{tc.name}' requires "
                            f"{PermissionLevel(tool.required_permission).name} level."
                        ),
                        is_error=True,
                    ))
                    continue

                log.info("tool_executing", tool=tc.name, args=tc.arguments)
                result: ToolResult = await tool.execute(**tc.arguments)
                output = result.output if result.success else f"Error: {result.error}"
                results.append(ToolCallResult(
                    id=tc.id, output=output, is_error=not result.success,
                ))

            current_messages.append(LLMMessage(role="user", tool_results=results))

        return response.content if response else ""
