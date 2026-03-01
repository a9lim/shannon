"""Tests for plan meta-tool."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from shannon.tools.plan_tool import PlanTool
from shannon.planner.engine import PlanEngine
from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMResponse


class TestPlanTool:
    def test_metadata(self):
        engine = MagicMock()
        tool = PlanTool(engine)
        assert tool.name == "plan"
        assert tool.required_permission == PermissionLevel.OPERATOR
        assert "goal" in tool.parameters["properties"]

    async def test_execute_creates_and_runs_plan(self, tmp_path):
        llm = AsyncMock()
        llm.count_tokens = MagicMock(return_value=10)
        llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"steps": [{"description": "Say hello", "tool": None}]}),
            tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
        ))
        engine = PlanEngine(llm=llm, tool_map={}, db_path=tmp_path / "plans.db")
        await engine.start()

        tool = PlanTool(engine)
        result = await tool.execute(goal="Test goal")
        assert result.success is True
        assert "completed" in result.output.lower()

        await engine.stop()

    async def test_execute_reports_failure(self, tmp_path):
        llm = AsyncMock()
        llm.count_tokens = MagicMock(return_value=10)
        # First call: create plan with a tool step referencing unknown tool
        # Second call: handle_failure returns abort
        llm.complete = AsyncMock(side_effect=[
            LLMResponse(
                content=json.dumps({"steps": [{"description": "Run cmd", "tool": "nonexistent"}]}),
                tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
            ),
            LLMResponse(
                content=json.dumps({"action": "abort"}),
                tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
            ),
        ])
        engine = PlanEngine(llm=llm, tool_map={}, db_path=tmp_path / "plans.db")
        await engine.start()

        tool = PlanTool(engine)
        result = await tool.execute(goal="Failing goal")
        assert result.success is False

        await engine.stop()
