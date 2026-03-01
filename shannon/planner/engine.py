"""Plan creation, execution, and persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine
from uuid import uuid4

import aiosqlite

from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMMessage, LLMProvider, LLMResponse
from shannon.planner.models import Plan, PlanStep
from shannon.tools.base import BaseTool
from shannon.utils.logging import get_logger

log = get_logger(__name__)

SendFn = Callable[[str, str, str], Coroutine[Any, Any, None]]

_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    status TEXT NOT NULL,
    channel TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_PLAN_PROMPT = """\
Decompose the following goal into 2-8 concrete steps. Each step should be \
a single action. For steps that use a tool, specify the tool name. \
For reasoning/analysis steps, set tool to null.

Available tools: {tools}

Respond with ONLY a JSON object:
{{"steps": [{{"description": "...", "tool": "tool_name_or_null"}}]}}

Goal: {goal}

Context: {context}
"""

_FAILURE_PROMPT = """\
Step {step_id} failed with error: {error}

Current plan state:
{plan_state}

Should we retry this step, skip it, or abort the plan?
Respond with ONLY a JSON object: {{"action": "retry" | "skip" | "abort"}}
"""

MAX_TOOL_INVOCATIONS = 15
MAX_STEPS = 8


class PlanEngine:
    def __init__(
        self,
        llm: LLMProvider,
        tool_map: dict[str, BaseTool],
        db_path: Path,
    ) -> None:
        self._llm = llm
        self._tool_map = tool_map
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(_PLAN_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def create_plan(
        self, goal: str, channel: str, context: str = ""
    ) -> Plan:
        tool_names = ", ".join(self._tool_map.keys()) or "none"
        prompt = _CREATE_PLAN_PROMPT.format(
            tools=tool_names, goal=goal, context=context or "No additional context.",
        )

        response = await self._llm.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            max_tokens=1024,
            temperature=0.3,
        )

        steps = self._parse_steps(response.content)
        plan_id = uuid4().hex[:12]
        plan = Plan(
            id=plan_id,
            goal=goal,
            steps=steps,
            status="planning",
            channel=channel,
        )
        await self.save_plan(plan)
        return plan

    def _parse_steps(self, content: str) -> list[PlanStep]:
        try:
            text = content.strip()
            if "```" in text:
                start = text.index("```") + 3
                if text[start:].startswith("json"):
                    start += 4
                end = text.index("```", start)
                text = text[start:end].strip()
            data = json.loads(text)
            raw_steps = data.get("steps", [])
        except (json.JSONDecodeError, ValueError, KeyError):
            log.warning("plan_parse_failed", content=content[:200])
            return [PlanStep(id=1, description="Execute the goal directly")]

        steps: list[PlanStep] = []
        for i, raw in enumerate(raw_steps[:MAX_STEPS], start=1):
            tool = raw.get("tool")
            if tool == "null" or tool is None:
                tool = None
            steps.append(PlanStep(
                id=i,
                description=raw.get("description", f"Step {i}"),
                tool=tool,
            ))
        return steps or [PlanStep(id=1, description="Execute the goal directly")]

    async def execute_plan(
        self,
        plan: Plan,
        user_level: PermissionLevel,
        send_fn: SendFn | None = None,
    ) -> Plan:
        plan.status = "executing"
        tool_invocations = 0

        for step in plan.steps:
            if tool_invocations >= MAX_TOOL_INVOCATIONS:
                step.status = "skipped"
                step.error = "Tool invocation cap reached"
                continue

            step.status = "running"
            plan.updated_at = datetime.now(timezone.utc)
            await self.save_plan(plan)

            if step.tool:
                tool = self._tool_map.get(step.tool)
                if not tool:
                    step.status = "failed"
                    step.error = f"Unknown tool: {step.tool}"
                    action = await self._handle_failure(plan, step)
                    if action == "abort":
                        plan.status = "failed"
                        break
                    elif action == "skip":
                        step.status = "skipped"
                    continue

                if user_level < tool.required_permission:
                    step.status = "failed"
                    step.error = f"Permission denied for {step.tool}"
                    action = await self._handle_failure(plan, step)
                    if action == "abort":
                        plan.status = "failed"
                        break
                    elif action == "skip":
                        step.status = "skipped"
                    continue

                result = await tool.execute(command=step.description)
                tool_invocations += 1

                if result.success:
                    step.status = "done"
                    step.result = result.output
                else:
                    step.status = "failed"
                    step.error = result.error
                    action = await self._handle_failure(plan, step)
                    if action == "abort":
                        plan.status = "failed"
                        break
                    elif action == "skip":
                        step.status = "skipped"
            else:
                # LLM reasoning step
                reasoning_prompt = (
                    f"Plan goal: {plan.goal}\n"
                    f"Current step: {step.description}\n"
                    f"Previous results: {self._summarize_results(plan)}"
                )
                response = await self._llm.complete(
                    messages=[LLMMessage(role="user", content=reasoning_prompt)],
                    max_tokens=512,
                    temperature=0.5,
                )
                step.status = "done"
                step.result = response.content

            # Send progress update
            if send_fn and plan.channel:
                parts = plan.channel.split(":", 1)
                if len(parts) == 2:
                    platform, channel = parts
                    done = sum(1 for s in plan.steps if s.status in ("done", "skipped", "failed"))
                    total = len(plan.steps)
                    status_icon = "+" if step.status == "done" else "x" if step.status == "failed" else "~"
                    await send_fn(
                        platform, channel,
                        f"Step {step.id}/{total} {step.status}: {step.description} [{status_icon}]",
                    )

        if plan.status != "failed":
            plan.status = "completed"

        plan.updated_at = datetime.now(timezone.utc)
        await self.save_plan(plan)
        return plan

    async def _handle_failure(self, plan: Plan, step: PlanStep) -> str:
        """Ask LLM whether to retry, skip, or abort after a failure."""
        plan_state = "\n".join(
            f"  {s.id}. [{s.status}] {s.description}" for s in plan.steps
        )
        prompt = _FAILURE_PROMPT.format(
            step_id=step.id, error=step.error, plan_state=plan_state,
        )
        try:
            response = await self._llm.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                max_tokens=64,
                temperature=0.1,
            )
            data = json.loads(response.content.strip())
            return data.get("action", "skip")
        except Exception:
            return "skip"

    def _summarize_results(self, plan: Plan) -> str:
        parts = []
        for step in plan.steps:
            if step.status == "done" and step.result:
                parts.append(f"Step {step.id}: {step.result[:200]}")
        return "\n".join(parts) or "No results yet."

    # --- Persistence ---

    async def save_plan(self, plan: Plan) -> None:
        assert self._db is not None
        steps_json = json.dumps([
            {
                "id": s.id, "description": s.description, "tool": s.tool,
                "status": s.status, "result": s.result, "error": s.error,
            }
            for s in plan.steps
        ])
        await self._db.execute(
            "INSERT INTO plans (id, goal, steps_json, status, channel, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET steps_json=?, status=?, updated_at=?",
            (
                plan.id, plan.goal, steps_json, plan.status, plan.channel,
                plan.created_at.isoformat(), plan.updated_at.isoformat(),
                steps_json, plan.status, plan.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def load_plan(self, plan_id: str) -> Plan | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, goal, steps_json, status, channel, created_at, updated_at "
            "FROM plans WHERE id = ?",
            (plan_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        steps_data = json.loads(row[2])
        steps = [
            PlanStep(
                id=s["id"], description=s["description"], tool=s.get("tool"),
                status=s.get("status", "pending"), result=s.get("result"),
                error=s.get("error"),
            )
            for s in steps_data
        ]
        return Plan(
            id=row[0], goal=row[1], steps=steps, status=row[3],
            channel=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
        )
