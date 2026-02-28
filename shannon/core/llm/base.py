"""LLM provider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from shannon.core.llm.types import LLMMessage, LLMResponse


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

    async def close(self) -> None:
        """Clean up resources. Override if needed."""
