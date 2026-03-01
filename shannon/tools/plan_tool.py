"""Plan meta-tool: create and execute multi-step plans."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.planner.engine import PlanEngine
from shannon.tools.base import BaseTool, ToolResult


class PlanTool(BaseTool):
    def __init__(self, engine: PlanEngine) -> None:
        self._engine = engine

    @property
    def name(self) -> str:
        return "plan"

    @property
    def description(self) -> str:
        return (
            "Create and execute a multi-step plan for a complex goal. "
            "Decomposes into steps, executes sequentially, reports progress."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The goal to accomplish.",
                },
            },
            "required": ["goal"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.OPERATOR

    async def execute(self, **kwargs: Any) -> ToolResult:
        goal = kwargs["goal"]

        try:
            plan = await self._engine.create_plan(goal, channel="")
            plan = await self._engine.execute_plan(
                plan, user_level=PermissionLevel.OPERATOR,
            )

            lines = [f"Plan: {plan.goal} [{plan.status}]"]
            for step in plan.steps:
                icon = {"done": "+", "failed": "x", "skipped": "~"}.get(step.status, "?")
                lines.append(f"  [{icon}] {step.description}")
                if step.result:
                    lines.append(f"      Result: {step.result[:200]}")
                if step.error:
                    lines.append(f"      Error: {step.error[:200]}")

            return ToolResult(
                success=plan.status == "completed",
                output="\n".join(lines),
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
