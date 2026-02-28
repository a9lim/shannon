"""Shared data types for the brain module."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    """A message in the conversation.

    ``content`` is ``str | list[dict[str, Any]]`` to support both plain text
    and Anthropic content blocks (needed for prompt caching / compaction).
    """
    role: str  # "system" | "user" | "assistant"
    content: str | list[dict[str, Any]]
    images: list[bytes] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LLMToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider."""
    text: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    stop_reason: str = ""
