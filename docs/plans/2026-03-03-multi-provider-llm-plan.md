# Multi-Provider LLM Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OpenAI (Responses API), Google Gemini, and OpenAI-compatible (Ollama, vLLM, LM Studio, etc.) LLM providers with a provider-agnostic internal message format.

**Architecture:** Refactor `LLMMessage` to carry `tool_calls` and `tool_results` as typed fields instead of Anthropic-format content blocks. Each provider translates between this neutral format and its wire format internally. Extract ReAct logic into a shared utility.

**Tech Stack:** `openai` SDK (OpenAI + compatible), `google-genai` SDK (Gemini), existing `anthropic` SDK, `tiktoken` for token counting.

---

### Task 1: Refactor LLMMessage — types and ToolExecutor

Make the internal message format provider-agnostic.

**Files:**
- Modify: `shannon/core/llm/types.py`
- Modify: `shannon/core/tool_executor.py`
- Modify: `tests/test_tool_executor.py`

**Step 1: Update types.py**

Add `ToolCallResult` and refactor `LLMMessage`:

```python
"""LLM data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "user", "assistant", "system"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolCallResult] = field(default_factory=list)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolCallResult:
    id: str  # matches ToolCall.id
    output: str
    is_error: bool = False


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
```

**Step 2: Update tool_executor.py**

Replace Anthropic content block construction with neutral fields:

```python
"""Tool-use loop: LLM calls with iterative tool execution."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.core.llm import LLMMessage, LLMProvider, LLMResponse
from shannon.core.llm.types import ToolCallResult
from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class ToolExecutor:
    """Runs the LLM completion + tool-use loop."""

    def __init__(self, llm: LLMProvider, tool_map: dict[str, BaseTool]) -> None:
        self._llm = llm
        self._tool_map = tool_map

    async def run(
        self,
        messages: list[LLMMessage],
        system: str,
        tool_schemas: list[dict[str, Any]],
        user_level: PermissionLevel,
        max_iterations: int = 10,
    ) -> str:
        """Run LLM completion with tool-use loop. Returns response text."""
        current_messages = list(messages)
        response: LLMResponse | None = None

        for _ in range(max_iterations):
            response = await self._llm.complete(
                messages=current_messages,
                system=system,
                tools=tool_schemas if tool_schemas else None,
            )

            # No tool calls — return the text
            if not response.tool_calls:
                return response.content

            # Add assistant message with tool calls
            current_messages.append(LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))

            # Execute tools and collect results
            results: list[ToolCallResult] = []
            for tc in response.tool_calls:
                tool = self._tool_map.get(tc.name)
                if not tool:
                    results.append(ToolCallResult(
                        id=tc.id,
                        output=f"Error: Unknown tool '{tc.name}'",
                        is_error=True,
                    ))
                    continue

                if user_level < tool.required_permission:
                    results.append(ToolCallResult(
                        id=tc.id,
                        output=(
                            f"Permission denied. Tool '{tc.name}' requires "
                            f"{PermissionLevel(tool.required_permission).name} level."
                        ),
                        is_error=True,
                    ))
                    continue

                log.info("tool_executing", tool=tc.name, args=tc.arguments)
                result: ToolResult = await tool.execute(**tc.arguments)
                output = result.output if result.success else f"Error: {result.error}"
                results.append(ToolCallResult(
                    id=tc.id, output=output, is_error=not result.success,
                ))

            current_messages.append(LLMMessage(role="user", tool_results=results))

        return response.content if response else ""
```

**Step 3: Update test_tool_executor.py**

The existing tests construct `LLMMessage(role="user", content="Hi")` which still works since `content` defaults to `""`. The tests should pass as-is because they only check inputs/outputs of the executor, not message internals. Run to verify:

Run: `pytest tests/test_tool_executor.py -v`
Expected: All 4 tests PASS

**Step 4: Commit**

```bash
git add shannon/core/llm/types.py shannon/core/tool_executor.py
git commit -m "refactor: make LLMMessage provider-agnostic with typed tool fields"
```

---

### Task 2: Rename to_anthropic_schema → to_schema

**Files:**
- Modify: `shannon/tools/base.py`
- Modify: `shannon/core/pipeline.py`

**Step 1: Rename in base.py**

In `shannon/tools/base.py`, rename `to_anthropic_schema` to `to_schema`:

```python
    def to_schema(self) -> dict[str, Any]:
        """Convert to generic tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
```

**Step 2: Update pipeline.py**

In `shannon/core/pipeline.py` line 84, change:
```python
        tool_schemas = [t.to_schema() for t in available_tools]
```

**Step 3: Run tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add shannon/tools/base.py shannon/core/pipeline.py
git commit -m "refactor: rename to_anthropic_schema to to_schema"
```

---

### Task 3: Update AnthropicProvider for new message format

The Anthropic provider must now translate `LLMMessage` with typed fields into Anthropic wire format.

**Files:**
- Modify: `shannon/core/llm/anthropic.py`

**Step 1: Update _build_kwargs to translate messages**

Replace the simple message pass-through with translation logic:

```python
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
            if msg.tool_calls:
                # Assistant message with tool calls
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                api_messages.append({"role": "assistant", "content": content})
            elif msg.tool_results:
                # Tool results message
                content = []
                for tr in msg.tool_results:
                    content.append({
                        "type": "tool_result",
                        "tool_use_id": tr.id,
                        "content": tr.output,
                        "is_error": tr.is_error,
                    })
                api_messages.append({"role": "user", "content": content})
            else:
                # Plain text message
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
```

**Step 2: Run tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add shannon/core/llm/anthropic.py
git commit -m "refactor: update AnthropicProvider for agnostic LLMMessage format"
```

---

### Task 4: Update LLMConfig and pyproject.toml

**Files:**
- Modify: `shannon/config.py`
- Modify: `pyproject.toml`
- Modify: `config.example.yaml`

**Step 1: Update LLMConfig**

```python
class LLMConfig(BaseModel):
    provider: str = "anthropic"  # "anthropic" | "openai" | "gemini" | "openai-compatible"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    base_url: str = ""  # for openai-compatible; provider defaults if empty
    max_tokens: int = 4096
    temperature: float = 0.7
    max_context_tokens: int = 100_000
    rate_limit_rpm: int = 50
    # Gemini Vertex AI (optional)
    project_id: str = ""
    location: str = "us-central1"
```

**Step 2: Update pyproject.toml optional deps**

Add to `[project.optional-dependencies]`:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.23",
]
openai = ["openai>=1.0"]
gemini = ["google-genai>=1.0"]
all-providers = ["openai>=1.0", "google-genai>=1.0"]
```

**Step 3: Update config.example.yaml**

```yaml
# Shannon configuration
# Copy to ~/.shannon/config.yaml or set SHANNON_CONFIG env var

llm:
  provider: anthropic          # "anthropic" | "openai" | "gemini" | "openai-compatible"
  model: claude-sonnet-4-20250514
  api_key: ""                  # or set SHANNON_LLM__API_KEY env var
  base_url: ""                 # for openai-compatible (e.g. http://localhost:11434/v1)
  max_tokens: 4096
  temperature: 0.7
  max_context_tokens: 100000

  # --- Provider-specific examples ---
  # OpenAI:
  #   provider: openai
  #   model: gpt-4o
  #   api_key: sk-...
  #
  # Google Gemini (API key):
  #   provider: gemini
  #   model: gemini-2.5-flash
  #   api_key: AIza...
  #
  # Google Gemini (Vertex AI):
  #   provider: gemini
  #   model: gemini-2.5-pro
  #   project_id: my-gcp-project
  #   location: us-central1
  #
  # Ollama:
  #   provider: openai-compatible
  #   model: llama3.1
  #   base_url: http://localhost:11434/v1
  #
  # vLLM / LM Studio / Together AI:
  #   provider: openai-compatible
  #   model: meta-llama/Llama-3.1-8B
  #   base_url: http://localhost:8000/v1
  #   api_key: ""

discord:
  token: ""                    # or set SHANNON_DISCORD__TOKEN env var
  guild_ids: []                # empty = all guilds
  command_prefix: "!"

signal:
  phone_number: ""             # Shannon's registered Signal number
  signal_cli_path: "signal-cli"
  rest_api_url: ""             # e.g. "http://localhost:8080" for signal-cli-rest-api
  mode: "cli"                  # "cli" or "rest"

auth:
  # Format: "platform:user_id" or bare "user_id" (applies to all platforms)
  admin_users: []
  operator_users: []
  trusted_users: []
  default_level: 0             # 0=public, 1=trusted, 2=operator, 3=admin
  rate_limit_per_minute: 30
  sudo_timeout_seconds: 300

scheduler:
  heartbeat_interval: 30
  enabled: true

chunker:
  discord_limit: 1900
  signal_limit: 2000
  typing_delay: 0.5
  typing_delay_ms_per_char: 50
  min_chunk_size: 100

browser:
  headless: true
  browser: "chromium"          # "chromium", "firefox", or "webkit"
  max_tabs: 5
  default_timeout: 30000

interactive:
  max_sessions: 5
  idle_timeout: 600
  max_output_size: 10000

log_level: INFO
log_json: false
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add shannon/config.py pyproject.toml config.example.yaml
git commit -m "feat: update config for multi-provider LLM support"
```

---

### Task 5: Extract ReAct utilities

Extract ReAct parsing from `local.py` into a shared module.

**Files:**
- Create: `shannon/core/llm/_react.py`
- Test: `tests/test_react.py`

**Step 1: Write tests for ReAct parsing**

```python
"""Tests for ReAct parsing utilities."""

import pytest

from shannon.core.llm._react import build_react_system, parse_react_response, flatten_messages
from shannon.core.llm.types import LLMMessage, ToolCall, ToolCallResult


class TestParseReactResponse:
    def test_no_action(self):
        content, calls = parse_react_response("Just a normal response.")
        assert content == "Just a normal response."
        assert calls == []

    def test_action_with_input(self):
        text = (
            "Let me check.\n"
            "Action: shell\n"
            'Action Input: {"command": "ls"}'
        )
        content, calls = parse_react_response(text)
        assert content == "Let me check."
        assert len(calls) == 1
        assert calls[0].name == "shell"
        assert calls[0].arguments == {"command": "ls"}

    def test_action_bad_json(self):
        text = "Action: shell\nAction Input: {bad json}"
        content, calls = parse_react_response(text)
        assert len(calls) == 1
        assert calls[0].arguments == {}


class TestBuildReactSystem:
    def test_no_tools(self):
        result = build_react_system("Base prompt", None)
        assert result == "Base prompt"

    def test_with_tools(self):
        tools = [{"name": "shell", "description": "Run commands", "input_schema": {}}]
        result = build_react_system("Base", tools)
        assert "shell" in result
        assert "Action:" in result


class TestFlattenMessages:
    def test_plain_message(self):
        msgs = [LLMMessage(role="user", content="hello")]
        result = flatten_messages(msgs, "System")
        assert result[0]["role"] == "system"
        assert result[1] == {"role": "user", "content": "hello"}

    def test_tool_call_message(self):
        msgs = [LLMMessage(
            role="assistant",
            content="Using tool",
            tool_calls=[ToolCall(id="t1", name="shell", arguments={"command": "ls"})],
        )]
        result = flatten_messages(msgs, None)
        assert "Action: shell" in result[0]["content"]

    def test_tool_result_message(self):
        msgs = [LLMMessage(
            role="user",
            tool_results=[ToolCallResult(id="t1", output="file.txt")],
        )]
        result = flatten_messages(msgs, None)
        assert "file.txt" in result[0]["content"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_react.py -v`
Expected: FAIL (module not found)

**Step 3: Implement _react.py**

```python
"""ReAct-style tool calling for models without native tool support."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from shannon.core.llm.types import LLMMessage, ToolCall

_REACT_ACTION_RE = re.compile(
    r"Action:\s*(\w+)\s*\nAction Input:\s*(\{.*?\})",
    re.DOTALL,
)


def build_react_system(system: str | None, tools: list[dict[str, Any]] | None) -> str:
    """Build a ReAct-style system prompt with tool descriptions."""
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


def parse_react_response(text: str) -> tuple[str, list[ToolCall]]:
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
        content = text[: match.start()].strip()
    else:
        content = text
    return content, tool_calls


def flatten_messages(
    messages: list[LLMMessage], system: str | None
) -> list[dict[str, Any]]:
    """Flatten LLMMessages with tool fields into plain text messages for ReAct mode."""
    api_messages: list[dict[str, Any]] = []

    if system:
        api_messages.append({"role": "system", "content": system})

    for msg in messages:
        if msg.tool_calls:
            parts = []
            if msg.content:
                parts.append(msg.content)
            for tc in msg.tool_calls:
                parts.append(f"Action: {tc.name}\nAction Input: {json.dumps(tc.arguments)}")
            api_messages.append({"role": msg.role, "content": "\n".join(parts)})
        elif msg.tool_results:
            parts = []
            for tr in msg.tool_results:
                prefix = "[Tool Error]: " if tr.is_error else "[Tool Result]: "
                parts.append(f"{prefix}{tr.output}")
            api_messages.append({"role": "user", "content": "\n".join(parts)})
        else:
            api_messages.append({"role": msg.role, "content": msg.content})

    return api_messages
```

**Step 4: Run tests**

Run: `pytest tests/test_react.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add shannon/core/llm/_react.py tests/test_react.py
git commit -m "feat: extract ReAct utilities into shared module"
```

---

### Task 6: OpenAI-Compatible Provider (Chat Completions)

Replaces `local.py`. Covers Ollama, vLLM, LM Studio, Together AI, etc.

**Files:**
- Create: `shannon/core/llm/openai_compat.py`
- Create: `tests/test_openai_compat_provider.py`

**Step 1: Write tests**

```python
"""Tests for OpenAI-compatible LLM provider."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shannon.config import LLMConfig
from shannon.core.llm.types import LLMMessage, ToolCall, ToolCallResult


class TestOpenAICompatibleProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(
            provider="openai-compatible",
            model="llama3.1",
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
        )

    @pytest.fixture
    def mock_openai_client(self):
        client = AsyncMock()
        return client

    @pytest.fixture
    def provider(self, config, mock_openai_client):
        with patch("shannon.core.llm.openai_compat.AsyncOpenAI", return_value=mock_openai_client):
            from shannon.core.llm.openai_compat import OpenAICompatibleProvider
            p = OpenAICompatibleProvider(config)
            p._client = mock_openai_client
            return p

    async def test_plain_completion(self, provider, mock_openai_client):
        # Mock response
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello!"
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await provider.complete(
            [LLMMessage(role="user", content="Hi")],
            system="Be helpful",
        )
        assert result.content == "Hello!"
        assert result.tool_calls == []

    async def test_tool_call_response(self, provider, mock_openai_client):
        mock_fn = MagicMock()
        mock_fn.name = "shell"
        mock_fn.arguments = '{"command": "ls"}'
        mock_tc = MagicMock()
        mock_tc.id = "call_123"
        mock_tc.type = "function"
        mock_tc.function = mock_fn

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.message.tool_calls = [mock_tc]
        mock_choice.finish_reason = "tool_calls"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 15
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await provider.complete(
            [LLMMessage(role="user", content="list files")],
            system="Be helpful",
            tools=[{"name": "shell", "description": "Run command", "input_schema": {"type": "object"}}],
        )
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "shell"
        assert result.tool_calls[0].arguments == {"command": "ls"}

    async def test_message_translation_with_tool_history(self, provider, mock_openai_client):
        """Verify messages with tool_calls/tool_results translate correctly."""
        mock_choice = MagicMock()
        mock_choice.message.content = "Done"
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage.prompt_tokens = 50
        mock_resp.usage.completion_tokens = 5
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        messages = [
            LLMMessage(role="user", content="list files"),
            LLMMessage(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "ls"})],
            ),
            LLMMessage(
                role="user",
                tool_results=[ToolCallResult(id="c1", output="a.txt\nb.txt")],
            ),
        ]
        await provider.complete(messages, system="sys")

        call_args = mock_openai_client.chat.completions.create.call_args
        api_msgs = call_args.kwargs["messages"]
        # system, user, assistant with tool_calls, tool result
        assert api_msgs[0]["role"] == "system"
        assert api_msgs[1]["role"] == "user"
        assert api_msgs[2]["role"] == "assistant"
        assert "tool_calls" in api_msgs[2]
        assert api_msgs[3]["role"] == "tool"
        assert api_msgs[3]["tool_call_id"] == "c1"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_openai_compat_provider.py -v`
Expected: FAIL (module not found)

**Step 3: Implement openai_compat.py**

```python
"""OpenAI-compatible LLM provider (Chat Completions API).

Covers Ollama, vLLM, LM Studio, Together AI, and any endpoint
that implements the OpenAI /v1/chat/completions format.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator
from uuid import uuid4

import tiktoken

from shannon.config import LLMConfig
from shannon.core.llm.base import LLMProvider
from shannon.core.llm.types import LLMMessage, LLMResponse, ToolCall
from shannon.core.llm._react import build_react_system, parse_react_response, flatten_messages
from shannon.utils.logging import get_logger

log = get_logger(__name__)

try:
    from openai import AsyncOpenAI, APIError, RateLimitError
except ImportError:
    raise ImportError(
        "The openai package is required for the openai-compatible provider. "
        "Install it with: pip install shannon[openai]"
    )


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI Chat Completions API provider."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._model = config.model
        base_url = config.base_url or "http://localhost:11434/v1"
        self._client = AsyncOpenAI(
            api_key=config.api_key or "not-needed",
            base_url=base_url,
        )
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
        api_messages = self._translate_messages(messages, system)
        api_tools = self._translate_tools(tools) if tools else None

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
        }
        if api_tools:
            kwargs["tools"] = api_tools

        response = await self._call_with_retry(kwargs)
        return self._parse_response(response, tools)

    async def stream(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        api_messages = self._translate_messages(messages, system)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._config.max_tokens,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "stream": True,
        }

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text))

    async def close(self) -> None:
        await self._client.close()

    def _translate_messages(
        self, messages: list[LLMMessage], system: str | None
    ) -> list[dict[str, Any]]:
        """Translate neutral LLMMessages to OpenAI Chat Completions format."""
        api_messages: list[dict[str, Any]] = []

        if system:
            api_messages.append({"role": "system", "content": system})

        for msg in messages:
            if msg.tool_calls:
                # Assistant message with tool calls
                api_tc = []
                for tc in msg.tool_calls:
                    api_tc.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    })
                api_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": api_tc,
                }
                api_messages.append(api_msg)
            elif msg.tool_results:
                # Each tool result becomes a separate "tool" role message
                for tr in msg.tool_results:
                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tr.id,
                        "content": tr.output,
                    })
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        return api_messages

    def _translate_tools(
        self, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Translate generic tool schemas to OpenAI function format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in tools
        ]

    def _parse_response(
        self, response: Any, tools: list[dict[str, Any]] | None
    ) -> LLMResponse:
        """Parse OpenAI response into LLMResponse."""
        choice = response.choices[0]
        msg = choice.message
        content_text = msg.content or ""

        tool_calls: list[ToolCall] = []
        native_tool_calls = msg.tool_calls or []

        if native_tool_calls:
            for tc in native_tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=tc.id or uuid4().hex[:12],
                    name=tc.function.name,
                    arguments=args,
                ))
        elif tools:
            # ReAct fallback
            content_text, tool_calls = parse_react_response(content_text)

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )

    async def _call_with_retry(
        self, kwargs: dict[str, Any], max_retries: int = 3
    ) -> Any:
        for attempt in range(max_retries + 1):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except RateLimitError:
                if attempt == max_retries:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("rate_limited", attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
            except APIError as e:
                if attempt == max_retries or (hasattr(e, "status_code") and e.status_code < 500):
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("api_error_retry", attempt=attempt)
                await asyncio.sleep(wait)
```

**Step 4: Run tests**

Run: `pytest tests/test_openai_compat_provider.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add shannon/core/llm/openai_compat.py tests/test_openai_compat_provider.py
git commit -m "feat: add OpenAI-compatible provider (Chat Completions)"
```

---

### Task 7: OpenAI Provider (Responses API)

**Files:**
- Create: `shannon/core/llm/openai.py`
- Create: `tests/test_openai_provider.py`

**Step 1: Write tests**

```python
"""Tests for OpenAI Responses API provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shannon.config import LLMConfig
from shannon.core.llm.types import LLMMessage, ToolCall, ToolCallResult


class TestOpenAIProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(provider="openai", model="gpt-4o", api_key="sk-test")

    @pytest.fixture
    def mock_openai_client(self):
        return AsyncMock()

    @pytest.fixture
    def provider(self, config, mock_openai_client):
        with patch("shannon.core.llm.openai.AsyncOpenAI", return_value=mock_openai_client):
            from shannon.core.llm.openai import OpenAIProvider
            p = OpenAIProvider(config)
            p._client = mock_openai_client
            return p

    async def test_plain_completion(self, provider, mock_openai_client):
        mock_output = MagicMock()
        mock_output.type = "message"
        mock_output.content = [MagicMock(type="output_text", text="Hello!")]

        mock_resp = MagicMock()
        mock_resp.output = [mock_output]
        mock_resp.usage.input_tokens = 10
        mock_resp.usage.output_tokens = 5
        mock_openai_client.responses.create = AsyncMock(return_value=mock_resp)

        result = await provider.complete(
            [LLMMessage(role="user", content="Hi")],
            system="Be helpful",
        )
        assert result.content == "Hello!"
        assert result.tool_calls == []

    async def test_function_call_response(self, provider, mock_openai_client):
        mock_fc = MagicMock()
        mock_fc.type = "function_call"
        mock_fc.id = "fc_123"
        mock_fc.call_id = "call_123"
        mock_fc.name = "shell"
        mock_fc.arguments = '{"command": "ls"}'

        mock_resp = MagicMock()
        mock_resp.output = [mock_fc]
        mock_resp.usage.input_tokens = 10
        mock_resp.usage.output_tokens = 15
        mock_openai_client.responses.create = AsyncMock(return_value=mock_resp)

        result = await provider.complete(
            [LLMMessage(role="user", content="list files")],
            system="Be helpful",
            tools=[{"name": "shell", "description": "Run command", "input_schema": {"type": "object"}}],
        )
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "shell"
        assert result.tool_calls[0].id == "call_123"

    async def test_message_with_tool_history(self, provider, mock_openai_client):
        mock_output = MagicMock()
        mock_output.type = "message"
        mock_output.content = [MagicMock(type="output_text", text="Done")]

        mock_resp = MagicMock()
        mock_resp.output = [mock_output]
        mock_resp.usage.input_tokens = 50
        mock_resp.usage.output_tokens = 5
        mock_openai_client.responses.create = AsyncMock(return_value=mock_resp)

        messages = [
            LLMMessage(role="user", content="list files"),
            LLMMessage(
                role="assistant",
                tool_calls=[ToolCall(id="call_1", name="shell", arguments={"command": "ls"})],
            ),
            LLMMessage(
                role="user",
                tool_results=[ToolCallResult(id="call_1", output="a.txt")],
            ),
        ]
        await provider.complete(messages, system="sys")

        call_args = mock_openai_client.responses.create.call_args
        api_input = call_args.kwargs["input"]
        # Should contain: user msg, function_call, function_call_output
        types = [item["type"] if isinstance(item, dict) else item.get("type", item.get("role")) for item in api_input]
        assert "message" in str(types) or "user" in str(types)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_openai_provider.py -v`
Expected: FAIL (module not found)

**Step 3: Implement openai.py**

```python
"""OpenAI LLM provider (Responses API)."""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator

import tiktoken

from shannon.config import LLMConfig
from shannon.core.llm.base import LLMProvider
from shannon.core.llm.types import LLMMessage, LLMResponse, ToolCall
from shannon.utils.logging import get_logger

log = get_logger(__name__)

try:
    from openai import AsyncOpenAI, APIError, RateLimitError
except ImportError:
    raise ImportError(
        "The openai package is required for the openai provider. "
        "Install it with: pip install shannon[openai]"
    )


class OpenAIProvider(LLMProvider):
    """OpenAI Responses API provider."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._model = config.model
        self._client = AsyncOpenAI(api_key=config.api_key)
        try:
            self._tokenizer = tiktoken.encoding_for_model(config.model)
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
        api_input = self._translate_messages(messages)
        api_tools = self._translate_tools(tools) if tools else None

        kwargs: dict[str, Any] = {
            "model": self._model,
            "input": api_input,
        }
        if system:
            kwargs["instructions"] = system
        if api_tools:
            kwargs["tools"] = api_tools
        if temperature is not None:
            kwargs["temperature"] = temperature
        else:
            kwargs["temperature"] = self._config.temperature
        if max_tokens or self._config.max_tokens:
            kwargs["max_output_tokens"] = max_tokens or self._config.max_tokens

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
        api_input = self._translate_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "input": api_input,
            "stream": True,
        }
        if system:
            kwargs["instructions"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        else:
            kwargs["temperature"] = self._config.temperature
        if max_tokens or self._config.max_tokens:
            kwargs["max_output_tokens"] = max_tokens or self._config.max_tokens

        stream = await self._client.responses.create(**kwargs)
        async for event in stream:
            if hasattr(event, "delta") and event.delta:
                yield event.delta

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text))

    async def close(self) -> None:
        await self._client.close()

    def _translate_messages(
        self, messages: list[LLMMessage]
    ) -> list[dict[str, Any]]:
        """Translate neutral LLMMessages to Responses API input items."""
        items: list[dict[str, Any]] = []

        for msg in messages:
            if msg.tool_calls:
                # First add any text content as a message
                if msg.content:
                    items.append({
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": msg.content}],
                    })
                # Then add each function call
                for tc in msg.tool_calls:
                    items.append({
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    })
            elif msg.tool_results:
                for tr in msg.tool_results:
                    items.append({
                        "type": "function_call_output",
                        "call_id": tr.id,
                        "output": tr.output,
                    })
            else:
                role = "user" if msg.role == "user" else "assistant"
                if msg.role == "system":
                    # System messages go in instructions, skip here
                    continue
                items.append({
                    "type": "message",
                    "role": role,
                    "content": [{"type": "input_text" if role == "user" else "output_text", "text": msg.content}],
                })

        return items

    def _translate_tools(
        self, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Translate generic tool schemas to Responses API function format."""
        return [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            }
            for t in tools
        ]

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Responses API output into LLMResponse."""
        result = LLMResponse(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "output_text":
                        result.content += part.text
            elif item.type == "function_call":
                args = item.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result.tool_calls.append(ToolCall(
                    id=item.call_id,
                    name=item.name,
                    arguments=args,
                ))

        if not result.tool_calls:
            result.stop_reason = "end_turn"
        else:
            result.stop_reason = "tool_use"

        return result

    async def _call_with_retry(
        self, kwargs: dict[str, Any], max_retries: int = 3
    ) -> Any:
        for attempt in range(max_retries + 1):
            try:
                return await self._client.responses.create(**kwargs)
            except RateLimitError:
                if attempt == max_retries:
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("rate_limited", attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
            except APIError as e:
                if attempt == max_retries or (hasattr(e, "status_code") and e.status_code < 500):
                    raise
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning("api_error_retry", attempt=attempt)
                await asyncio.sleep(wait)
```

**Step 4: Run tests**

Run: `pytest tests/test_openai_provider.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add shannon/core/llm/openai.py tests/test_openai_provider.py
git commit -m "feat: add OpenAI Responses API provider"
```

---

### Task 8: Gemini Provider

**Files:**
- Create: `shannon/core/llm/gemini.py`
- Create: `tests/test_gemini_provider.py`

**Step 1: Write tests**

```python
"""Tests for Google Gemini LLM provider."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


from shannon.config import LLMConfig
from shannon.core.llm.types import LLMMessage, ToolCall, ToolCallResult


class TestGeminiProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(
            provider="gemini",
            model="gemini-2.5-flash",
            api_key="test-key",
        )

    @pytest.fixture
    def mock_genai_client(self):
        return MagicMock()

    @pytest.fixture
    def provider(self, config, mock_genai_client):
        with patch("shannon.core.llm.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = mock_genai_client
            from shannon.core.llm.gemini import GeminiProvider
            p = GeminiProvider(config)
            p._client = mock_genai_client
            return p

    async def test_plain_completion(self, provider, mock_genai_client):
        mock_part = MagicMock()
        mock_part.text = "Hello!"
        mock_part.function_call = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_resp = MagicMock()
        mock_resp.candidates = [mock_candidate]
        mock_resp.usage_metadata.prompt_token_count = 10
        mock_resp.usage_metadata.candidates_token_count = 5

        mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        result = await provider.complete(
            [LLMMessage(role="user", content="Hi")],
            system="Be helpful",
        )
        assert result.content == "Hello!"
        assert result.tool_calls == []

    async def test_function_call_response(self, provider, mock_genai_client):
        mock_fc = MagicMock()
        mock_fc.name = "shell"
        mock_fc.args = {"command": "ls"}

        mock_part = MagicMock()
        mock_part.text = None
        mock_part.function_call = mock_fc

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_resp = MagicMock()
        mock_resp.candidates = [mock_candidate]
        mock_resp.usage_metadata.prompt_token_count = 10
        mock_resp.usage_metadata.candidates_token_count = 15

        mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        result = await provider.complete(
            [LLMMessage(role="user", content="list files")],
            system="Be helpful",
            tools=[{"name": "shell", "description": "Run command", "input_schema": {"type": "object"}}],
        )
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "shell"
        assert result.tool_calls[0].arguments == {"command": "ls"}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gemini_provider.py -v`
Expected: FAIL (module not found)

**Step 3: Implement gemini.py**

```python
"""Google Gemini LLM provider via google-genai SDK."""

from __future__ import annotations

import asyncio
import random
from typing import Any, AsyncIterator
from uuid import uuid4

from shannon.config import LLMConfig
from shannon.core.llm.base import LLMProvider
from shannon.core.llm.types import LLMMessage, LLMResponse, ToolCall
from shannon.utils.logging import get_logger

log = get_logger(__name__)

try:
    from google import genai
    from google.genai import types
except ImportError:
    raise ImportError(
        "The google-genai package is required for the gemini provider. "
        "Install it with: pip install shannon[gemini]"
    )


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._model = config.model

        if config.project_id:
            # Vertex AI
            self._client = genai.Client(
                vertexai=True,
                project=config.project_id,
                location=config.location or "us-central1",
            )
        else:
            # Gemini Developer API
            self._client = genai.Client(api_key=config.api_key)

    async def complete(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        contents = self._translate_messages(messages)
        config = self._build_config(system, tools, temperature, max_tokens)

        response = await self._call_with_retry(contents, config)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[LLMMessage],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        contents = self._translate_messages(messages)
        config = self._build_config(system, tools, temperature, max_tokens)

        async for chunk in await self._client.aio.models.generate_content_stream(
            model=self._model, contents=contents, config=config,
        ):
            if chunk.candidates and chunk.candidates[0].content.parts:
                for part in chunk.candidates[0].content.parts:
                    if part.text:
                        yield part.text

    def count_tokens(self, text: str) -> int:
        # Use Gemini's token counting API synchronously via a helper
        # Fall back to rough estimate if API unavailable
        try:
            response = self._client.models.count_tokens(
                model=self._model, contents=text,
            )
            return response.total_tokens
        except Exception:
            return len(text) // 4  # rough estimate

    async def close(self) -> None:
        pass  # google-genai client has no explicit close

    def _translate_messages(
        self, messages: list[LLMMessage]
    ) -> list[types.Content]:
        """Translate neutral LLMMessages to Gemini Content objects."""
        contents: list[types.Content] = []

        for msg in messages:
            role = "model" if msg.role == "assistant" else "user"

            if msg.tool_calls:
                # Model message with function calls
                parts = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(types.Part(
                        function_call=types.FunctionCall(
                            name=tc.name, args=tc.arguments,
                        )
                    ))
                contents.append(types.Content(role="model", parts=parts))
            elif msg.tool_results:
                # User message with function responses
                parts = []
                for tr in msg.tool_results:
                    parts.append(types.Part.from_function_response(
                        name=tr.id,  # Gemini uses function name, we pass id
                        response={"result": tr.output, "is_error": tr.is_error},
                    ))
                contents.append(types.Content(role="user", parts=parts))
            elif msg.role != "system":
                # Plain text (skip system — handled via config)
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg.content)],
                ))

        return contents

    def _build_config(
        self,
        system: str | None,
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> types.GenerateContentConfig:
        """Build Gemini generation config."""
        kwargs: dict[str, Any] = {}

        if system:
            kwargs["system_instruction"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        else:
            kwargs["temperature"] = self._config.temperature
        if max_tokens or self._config.max_tokens:
            kwargs["max_output_tokens"] = max_tokens or self._config.max_tokens

        if tools:
            gemini_tools = types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("input_schema", {}),
                )
                for t in tools
            ])
            kwargs["tools"] = [gemini_tools]

        return types.GenerateContentConfig(**kwargs)

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Gemini response into LLMResponse."""
        result = LLMResponse()

        try:
            result.input_tokens = response.usage_metadata.prompt_token_count
            result.output_tokens = response.usage_metadata.candidates_token_count
        except (AttributeError, TypeError):
            pass

        if not response.candidates:
            return result

        parts = response.candidates[0].content.parts
        for part in parts:
            if part.function_call:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                result.tool_calls.append(ToolCall(
                    id=uuid4().hex[:12],
                    name=fc.name,
                    arguments=args,
                ))
            elif part.text:
                result.content += part.text

        result.stop_reason = "tool_use" if result.tool_calls else "end_turn"
        return result

    async def _call_with_retry(
        self, contents: list[types.Content], config: types.GenerateContentConfig,
        max_retries: int = 3,
    ) -> Any:
        for attempt in range(max_retries + 1):
            try:
                return await self._client.aio.models.generate_content(
                    model=self._model, contents=contents, config=config,
                )
            except Exception as e:
                err_str = str(e).lower()
                if attempt == max_retries:
                    raise
                if "rate" in err_str or "429" in err_str or "500" in err_str or "503" in err_str:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    log.warning("gemini_retry", attempt=attempt, error=str(e))
                    await asyncio.sleep(wait)
                else:
                    raise
```

**Step 4: Run tests**

Run: `pytest tests/test_gemini_provider.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add shannon/core/llm/gemini.py tests/test_gemini_provider.py
git commit -m "feat: add Google Gemini provider"
```

---

### Task 9: Update factory, delete local.py, update __init__.py

**Files:**
- Modify: `shannon/core/llm/__init__.py`
- Delete: `shannon/core/llm/local.py`

**Step 1: Rewrite __init__.py**

```python
"""LLM provider subpackage."""

from shannon.core.llm.types import LLMMessage, LLMResponse, ToolCall, ToolCallResult
from shannon.core.llm.base import LLMProvider
from shannon.core.llm.anthropic import AnthropicProvider
from shannon.config import LLMConfig

__all__ = [
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolCallResult",
    "LLMProvider",
    "AnthropicProvider",
    "create_provider",
]


def create_provider(config: LLMConfig) -> LLMProvider:
    """Factory to create the appropriate LLM provider from config."""
    if config.provider == "anthropic":
        return AnthropicProvider(config)
    elif config.provider == "openai":
        from shannon.core.llm.openai import OpenAIProvider
        return OpenAIProvider(config)
    elif config.provider == "gemini":
        from shannon.core.llm.gemini import GeminiProvider
        return GeminiProvider(config)
    elif config.provider == "openai-compatible":
        from shannon.core.llm.openai_compat import OpenAICompatibleProvider
        return OpenAICompatibleProvider(config)
    else:
        raise ValueError(
            f"Unknown LLM provider: '{config.provider}'. "
            f"Supported: anthropic, openai, gemini, openai-compatible"
        )
```

**Step 2: Delete local.py**

```bash
rm shannon/core/llm/local.py
```

**Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS (nothing imports LocalProvider directly in tests)

**Step 4: Commit**

```bash
git add shannon/core/llm/__init__.py
git rm shannon/core/llm/local.py
git commit -m "refactor: update provider factory, remove LocalProvider"
```

---

### Task 10: Update Gemini tool_results to use function name

The Gemini API's `Part.from_function_response` requires the function **name**, not the tool call ID. We need to carry the function name through `ToolCallResult` so Gemini can use it.

**Files:**
- Modify: `shannon/core/llm/types.py`
- Modify: `shannon/core/tool_executor.py`
- Modify: `shannon/core/llm/gemini.py`

**Step 1: Add `name` field to ToolCallResult**

In `types.py`, update `ToolCallResult`:

```python
@dataclass
class ToolCallResult:
    id: str  # matches ToolCall.id
    output: str
    is_error: bool = False
    name: str = ""  # tool name, needed by Gemini
```

**Step 2: Set name in ToolExecutor**

In `tool_executor.py`, when creating `ToolCallResult`, add the tool name:

```python
                results.append(ToolCallResult(
                    id=tc.id, output=output, is_error=not result.success, name=tc.name,
                ))
```

Also for error/permission cases:
```python
                    results.append(ToolCallResult(
                        id=tc.id, output=f"Error: Unknown tool '{tc.name}'", is_error=True, name=tc.name,
                    ))
```
```python
                    results.append(ToolCallResult(
                        id=tc.id,
                        output=f"Permission denied...",
                        is_error=True,
                        name=tc.name,
                    ))
```

**Step 3: Use name in Gemini provider**

In `gemini.py`, update `_translate_messages` tool_results section:

```python
                    parts.append(types.Part.from_function_response(
                        name=tr.name,
                        response={"result": tr.output, "is_error": tr.is_error},
                    ))
```

**Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add shannon/core/llm/types.py shannon/core/tool_executor.py shannon/core/llm/gemini.py
git commit -m "fix: carry tool name in ToolCallResult for Gemini compatibility"
```

---

### Task 11: Update CLAUDE.md and README

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Update CLAUDE.md**

Update the LLM subpackage description:
- Replace `local.py (LocalProvider + ReAct)` with new providers
- Update `types.py` description to include `ToolCallResult`
- Update `__init__.py` description
- Update "Adding New Components — New LLM provider" section
- Update config documentation

**Step 2: Update README.md**

Update the LLM config table to show all 4 providers and new fields.

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update architecture docs for multi-provider LLM support"
```

---

### Task 12: Final integration test

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify imports**

Run: `python -c "from shannon.core.llm import create_provider, LLMMessage, ToolCallResult; print('OK')"`
Expected: `OK`

**Step 3: Verify factory error handling**

Run: `python -c "from shannon.core.llm import create_provider; from shannon.config import LLMConfig; create_provider(LLMConfig(provider='bogus'))"`
Expected: `ValueError: Unknown LLM provider: 'bogus'`

**Step 4: Final commit if any cleanup needed**

---

Plan complete and saved to `docs/plans/2026-03-03-multi-provider-llm-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?