"""Planner data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class PlanStep:
    id: int
    description: str
    tool: str | None = None
    parameters: dict[str, str] | None = None
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    result: str | None = None
    error: str | None = None


@dataclass
class Plan:
    id: str
    goal: str
    steps: list[PlanStep]
    status: Literal["planning", "executing", "completed", "failed"] = "planning"
    channel: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
