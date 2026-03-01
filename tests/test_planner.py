"""Tests for multi-step task planner."""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from shannon.planner.models import PlanStep, Plan
from shannon.planner.engine import PlanEngine
from shannon.core.llm import LLMResponse, LLMMessage
from shannon.core.auth import PermissionLevel
from shannon.tools.base import ToolResult


class TestPlanModels:
    def test_plan_step_defaults(self):
        step = PlanStep(id=1, description="Do something")
        assert step.status == "pending"
        assert step.tool is None
        assert step.result is None
        assert step.error is None

    def test_plan_creation(self):
        steps = [
            PlanStep(id=1, description="Step 1", tool="shell"),
            PlanStep(id=2, description="Step 2"),
        ]
        plan = Plan(
            id="plan-1",
            goal="Deploy app",
            steps=steps,
            status="planning",
            channel="discord:123",
        )
        assert plan.goal == "Deploy app"
        assert len(plan.steps) == 2
        assert plan.status == "planning"

    def test_plan_step_status_values(self):
        for status in ("pending", "running", "done", "failed", "skipped"):
            step = PlanStep(id=1, description="test", status=status)
            assert step.status == status

    def test_plan_has_timestamps(self):
        plan = Plan(id="p1", goal="test", steps=[])
        assert isinstance(plan.created_at, datetime)
        assert isinstance(plan.updated_at, datetime)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.count_tokens = MagicMock(return_value=10)
    return llm


@pytest.fixture
def mock_tool_map():
    tool = AsyncMock()
    tool.name = "shell"
    tool.required_permission = PermissionLevel.OPERATOR
    tool.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
    return {"shell": tool}


@pytest.fixture
async def engine(tmp_path, mock_llm, mock_tool_map):
    e = PlanEngine(
        llm=mock_llm,
        tool_map=mock_tool_map,
        db_path=tmp_path / "plans.db",
    )
    await e.start()
    yield e
    await e.stop()


class TestPlanCreation:
    async def test_create_plan(self, engine, mock_llm):
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "steps": [
                    {"description": "List files", "tool": "shell"},
                    {"description": "Analyze output", "tool": None},
                ]
            }),
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        ))
        plan = await engine.create_plan("Find large files", channel="discord:123")
        assert plan.goal == "Find large files"
        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "shell"
        assert plan.status == "planning"

    async def test_create_plan_caps_steps(self, engine, mock_llm):
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({
                "steps": [{"description": f"Step {i}", "tool": "shell"} for i in range(12)]
            }),
            tool_calls=[], stop_reason="end_turn", input_tokens=100, output_tokens=50,
        ))
        plan = await engine.create_plan("Big task", channel="discord:123")
        assert len(plan.steps) <= 8

    async def test_create_plan_bad_json(self, engine, mock_llm):
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content="not valid json at all",
            tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
        ))
        plan = await engine.create_plan("Test", channel="discord:123")
        assert len(plan.steps) == 1  # Fallback step


class TestPlanExecution:
    async def test_execute_plan_success(self, engine, mock_llm, mock_tool_map):
        plan = Plan(
            id="test-1",
            goal="Test",
            steps=[
                PlanStep(id=1, description="Run ls", tool="shell"),
                PlanStep(id=2, description="Think about it"),
            ],
            status="executing",
            channel="discord:123",
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content="Looks good", tool_calls=[], stop_reason="end_turn",
            input_tokens=10, output_tokens=10,
        ))

        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        assert result.status == "completed"
        assert result.steps[0].status == "done"
        assert result.steps[1].status == "done"

    async def test_execute_plan_tool_failure(self, engine, mock_llm, mock_tool_map):
        mock_tool_map["shell"].execute = AsyncMock(
            return_value=ToolResult(success=False, error="command not found")
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"action": "skip"}),
            tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
        ))

        plan = Plan(
            id="test-2",
            goal="Test",
            steps=[
                PlanStep(id=1, description="Run bad cmd", tool="shell"),
                PlanStep(id=2, description="Next step", tool="shell"),
            ],
            status="executing",
            channel="discord:123",
        )
        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        assert result.steps[0].status == "skipped"  # failed then skipped

    async def test_execute_plan_abort(self, engine, mock_llm, mock_tool_map):
        mock_tool_map["shell"].execute = AsyncMock(
            return_value=ToolResult(success=False, error="critical error")
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content=json.dumps({"action": "abort"}),
            tool_calls=[], stop_reason="end_turn", input_tokens=10, output_tokens=10,
        ))

        plan = Plan(
            id="test-abort",
            goal="Test",
            steps=[
                PlanStep(id=1, description="Fail", tool="shell"),
                PlanStep(id=2, description="Never reached", tool="shell"),
            ],
            status="executing",
            channel="discord:123",
        )
        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        assert result.status == "failed"
        assert result.steps[1].status == "pending"  # never reached

    async def test_tool_invocation_cap(self, engine, mock_llm, mock_tool_map):
        plan = Plan(
            id="test-3",
            goal="Test",
            steps=[PlanStep(id=i, description=f"Step {i}", tool="shell") for i in range(16)],
            status="executing",
            channel="discord:123",
        )
        mock_llm.complete = AsyncMock(return_value=LLMResponse(
            content="ok", tool_calls=[], stop_reason="end_turn",
            input_tokens=10, output_tokens=10,
        ))
        send = AsyncMock()
        result = await engine.execute_plan(plan, user_level=PermissionLevel.OPERATOR, send_fn=send)
        done_count = sum(1 for s in result.steps if s.status == "done")
        assert done_count <= 15


class TestPlanPersistence:
    async def test_save_and_load_plan(self, engine):
        plan = Plan(
            id="persist-1",
            goal="Persist test",
            steps=[PlanStep(id=1, description="Step 1", tool="shell")],
            status="executing",
            channel="discord:123",
        )
        await engine.save_plan(plan)
        loaded = await engine.load_plan("persist-1")
        assert loaded is not None
        assert loaded.goal == "Persist test"
        assert len(loaded.steps) == 1
        assert loaded.steps[0].tool == "shell"

    async def test_load_nonexistent(self, engine):
        loaded = await engine.load_plan("nonexistent")
        assert loaded is None

    async def test_update_plan(self, engine):
        plan = Plan(
            id="update-1",
            goal="Update test",
            steps=[PlanStep(id=1, description="Step 1")],
            status="planning",
            channel="discord:123",
        )
        await engine.save_plan(plan)
        plan.status = "executing"
        await engine.save_plan(plan)
        loaded = await engine.load_plan("update-1")
        assert loaded.status == "executing"
