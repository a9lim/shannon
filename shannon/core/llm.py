"""LLM provider abstraction with Anthropic and local implementations."""

from __future__ import annotations

import asyncio
import json
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx
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

    async def close(self) -> None:
        """Clean up resources. Override if needed."""


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

    async def close(self) -> None:
        await self._client.close()

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
            except RateLimitError:
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


# ---------------------------------------------------------------------------
# ReAct-style tool call parsing for models without native tool support
# ---------------------------------------------------------------------------

_REACT_ACTION_RE = re.compile(
    r"Action:\s*(\w+)\s*\nAction Input:\s*(\{.*?\})",
    re.DOTALL,
)


def _build_react_system(system: str | None, tools: list[dict[str, Any]] | None) -> str:
    """Build a ReAct-style system prompt for models without native tool calling."""
    parts: list[str] = []
    if system:
        parts.append(system)

    if tools:
        parts.append("\n\n## Tools\nYou have the following tools. To use one, respond with:\n")
        parts.append("Thought: <your reasoning>\nAction: <tool_name>\nAction Input: <json arguments>\n")
        parts.append("When you have a final answer, respond normally without Action/Action Input.\n")
        for tool in tools:
            schema = json.dumps(tool.get("input_schema", {}), indent=2)
            parts.append(f"### {tool['name']}\n{tool.get('description', '')}\nParameters: {schema}\n")

    return "\n".join(parts)


def _parse_react_response(text: str) -> tuple[str, list[ToolCall]]:
    """Parse ReAct-formatted text into content and tool calls."""
    tool_calls: list[ToolCall] = []
    match = _REACT_ACTION_RE.search(text)
    if match:
        tool_name = match.group(1)
        try:
            args = json.loads(match.group(2))
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(id=uuid4().hex[:12], name=tool_name, arguments=args))
        # Content is everything before the Action line
        content = text[: match.start()].strip()
    else:
        content = text

    return content, tool_calls


class LocalProvider(LLMProvider):
    """OpenAI-compatible local model provider (ollama, llama.cpp, vllm, etc.)."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._endpoint = config.local_endpoint.rstrip("/")
        self._model = config.model
        self._client = httpx.AsyncClient(timeout=120, base_url=self._endpoint)
        try:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
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
        # Try native tool calling first; fall back to ReAct
        api_messages = self._build_messages(messages, system, tools)
        body: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }

        resp = await self._post_with_retry("/chat/completions", body)
        data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]
        content_text = msg.get("content", "") or ""

        # Check for native tool calls in response
        native_tool_calls = msg.get("tool_calls", [])
        tool_calls: list[ToolCall] = []

        if native_tool_calls:
            for tc in native_tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", uuid4().hex[:12]),
                    name=fn.get("name", ""),
                    arguments=args,
                ))
        elif tools:
            # Fall back to ReAct parsing
            content_text, tool_calls = _parse_react_response(content_text)

        usage = data.get("usage", {})
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        api_messages = self._build_messages(messages, system, tools)
        body: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "stream": True,
        }

        async with self._client.stream("POST", "/chat/completions", json=body) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text))

    async def close(self) -> None:
        await self._client.aclose()

    def _build_messages(
        self,
        messages: list[LLMMessage],
        system: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []

        # For ReAct mode, inject tool info into system prompt
        effective_system = _build_react_system(system, tools) if tools else system
        if effective_system:
            api_messages.append({"role": "system", "content": effective_system})

        for msg in messages:
            content = msg.content
            if isinstance(content, list):
                # Flatten structured content to text for local models
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_result":
                            text_parts.append(f"[Tool Result]: {block.get('content', '')}")
                        elif block.get("type") == "tool_use":
                            text_parts.append(
                                f"Action: {block.get('name', '')}\n"
                                f"Action Input: {json.dumps(block.get('input', {}))}"
                            )
                content = "\n".join(text_parts)
            api_messages.append({"role": msg.role, "content": content})

        return api_messages

    async def _post_with_retry(
        self, path: str, body: dict[str, Any], max_retries: int = 2
    ) -> httpx.Response:
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post(path, json=body)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                if attempt == max_retries or e.response.status_code < 500:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("local_llm_retry", status=e.response.status_code, attempt=attempt)
                await asyncio.sleep(wait)
            except httpx.ConnectError:
                if attempt == max_retries:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("local_llm_connect_retry", attempt=attempt)
                await asyncio.sleep(wait)
        raise RuntimeError("Unreachable")


def create_provider(config: LLMConfig) -> LLMProvider:
    """Factory to create the appropriate LLM provider from config."""
    if config.provider == "local":
        return LocalProvider(config)
    return AnthropicProvider(config)
