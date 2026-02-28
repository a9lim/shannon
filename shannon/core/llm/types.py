"""LLM data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "user", "assistant", "system"
    content: str | list[dict[str, Any]]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
