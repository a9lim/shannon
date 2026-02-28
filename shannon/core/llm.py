"""LLM provider abstraction with Anthropic implementation."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import tiktoken
from anthropic import AsyncAnthropic, APIError, RateLimitError

from shannon.config import LLMConfig
from shannon.utils.logging import get_logger

log = get_logger(__name__)


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


class AnthropicProvider(LLMProvider):
    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = AsyncAnthropic(api_key=config.api_key)
        self._model = config.model
        try:
            self._tokenizer = tiktoken.encoding_for_model("cl100k_base")
        except Exception:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")

    async def complete(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, system, tools, temperature, max_tokens)
        response = await self._call_with_retry(kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        kwargs = self._build_kwargs(messages, system, tools, temperature, max_tokens)
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text))

    def _build_kwargs(
        self,
        messages: list[LLMMessage],
        system: str | None,
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        api_messages = []
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        return kwargs

    async def _call_with_retry(
        self, kwargs: dict[str, Any], max_retries: int = 3
    ) -> Any:
        for attempt in range(max_retries + 1):
            try:
                return await self._client.messages.create(**kwargs)
            except RateLimitError as e:
                if attempt == max_retries:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("rate_limited", attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
            except APIError as e:
                if attempt == max_retries or e.status_code < 500:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("api_error_retry", status=e.status_code, attempt=attempt)
                await asyncio.sleep(wait)

    def _parse_response(self, response: Any) -> LLMResponse:
        result = LLMResponse(
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        for block in response.content:
            if block.type == "text":
                result.content += block.text
            elif block.type == "tool_use":
                result.tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        return result

    @staticmethod
    def convert_tool_schema(
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a Shannon tool definition to Anthropic tool format."""
        return {
            "name": name,
            "description": description,
            "input_schema": parameters,
        }
