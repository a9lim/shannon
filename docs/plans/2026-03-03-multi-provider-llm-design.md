# Multi-Provider LLM Support Design

**Date:** 2026-03-03
**Status:** Approved

## Goal

Add support for OpenAI (Responses API), Google Gemini, and OpenAI-compatible endpoints (Ollama, vLLM, LM Studio, Together AI, etc.) alongside the existing Anthropic provider. Remove the old `LocalProvider` in favor of a proper `OpenAICompatibleProvider`.

## Providers

| Provider | Config name | SDK | Covers |
|---|---|---|---|
| `AnthropicProvider` | `anthropic` | `anthropic` | Claude models |
| `OpenAIProvider` | `openai` | `openai` | GPT models (Responses API) |
| `GeminiProvider` | `gemini` | `google-genai` | Gemini models |
| `OpenAICompatibleProvider` | `openai-compatible` | `openai` | Ollama, vLLM, LM Studio, Together, etc. |

## Agnostic Internal Message Format

The internal `LLMMessage` becomes provider-agnostic with first-class tool fields:

```python
@dataclass
class ToolCallResult:
    id: str            # matches ToolCall.id
    output: str
    is_error: bool = False

@dataclass
class LLMMessage:
    role: str  # "user", "assistant", "system"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolCallResult] = field(default_factory=list)
```

Each provider translates between this neutral model and its wire format inside `complete()`. No provider-specific logic in ToolExecutor or pipeline.

### Tool Schema Format

`BaseTool.to_anthropic_schema()` renamed to `to_schema()`. Returns a generic format:
```python
{"name": "...", "description": "...", "input_schema": {"type": "object", ...}}
```

Each provider converts this to its API-specific tool format internally.

## Message Translation Per Provider

### Anthropic
- Tools: `{"name", "description", "input_schema"}` used as-is
- Messages: builds structured content blocks (`tool_use`, `tool_result`) from `LLMMessage` fields
- System: passed as `system` parameter

### OpenAI (Responses API)
- Tools: `{"type": "function", "name", "description", "parameters"}`
- System: `instructions` parameter
- `tool_calls` → `function_call` items
- `tool_results` → `function_call_output` items

### Gemini (google-genai)
- Tools: `types.Tool(function_declarations=[types.FunctionDeclaration(...)])`
- System: `GenerateContentConfig(system_instruction=...)`
- `tool_calls` → `Content(role="model", parts=[Part(function_call=...)])`
- `tool_results` → `Content(role="user", parts=[Part.from_function_response(...)])`

### OpenAI-Compatible (Chat Completions)
- Tools: `{"type": "function", "function": {"name", "description", "parameters"}}`
- System: `{"role": "system", "content": "..."}`
- `tool_calls` → `{"role": "assistant", "tool_calls": [...]}`
- `tool_results` → `{"role": "tool", "tool_call_id", "content"}`
- ReAct fallback: flattens to text, injects tool descriptions into system prompt

## ReAct Fallback

Extracted from `local.py` into `_react.py` as a shared utility:
- `build_react_system()` — injects tool descriptions into system prompt
- `parse_react_response()` — regex parses `Action: / Action Input:` from text
- `flatten_messages()` — converts messages with tool_calls/tool_results to plain text

Used by `OpenAICompatibleProvider` when a model doesn't return native tool calls.

## Config

```python
class LLMConfig(BaseModel):
    provider: str = "anthropic"  # "anthropic" | "openai" | "gemini" | "openai-compatible"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    base_url: str = ""           # for openai-compatible; defaults per provider if empty
    max_tokens: int = 4096
    temperature: float = 0.7
    max_context_tokens: int = 100_000
    rate_limit_rpm: int = 50
    project_id: str = ""         # Gemini Vertex AI
    location: str = "us-central1"  # Gemini Vertex AI
```

Environment variables: `SHANNON_LLM__PROVIDER=openai`, `SHANNON_LLM__BASE_URL=http://...`, etc.

## Dependencies

Optional extras so users only install what they need:
```
openai = ["openai>=1.0"]
gemini = ["google-genai>=1.0"]
all = ["openai>=1.0", "google-genai>=1.0"]
```

Lazy imports in the factory with clear error messages if SDK is missing.

## File Changes

| File | Action | What changes |
|---|---|---|
| `core/llm/types.py` | Edit | Add `ToolCallResult`. `LLMMessage` gets `tool_calls`, `tool_results` fields, `content` becomes `str` |
| `core/llm/anthropic.py` | Edit | Translate neutral LLMMessage to/from Anthropic wire format |
| `core/llm/openai.py` | New | OpenAI Responses API provider |
| `core/llm/gemini.py` | New | Google Gemini provider via google-genai SDK |
| `core/llm/openai_compat.py` | New | Chat Completions provider with ReAct fallback |
| `core/llm/_react.py` | New | Extracted ReAct utilities |
| `core/llm/local.py` | Delete | Replaced by openai_compat.py + _react.py |
| `core/llm/__init__.py` | Edit | Updated factory, exports |
| `core/tool_executor.py` | Edit | Use LLMMessage fields instead of Anthropic content blocks |
| `core/pipeline.py` | Edit | `to_schema()` instead of `to_anthropic_schema()` |
| `tools/base.py` | Edit | Rename `to_anthropic_schema()` to `to_schema()` |
| `config.py` | Edit | Update LLMConfig fields |
| `config.example.yaml` | Edit | Add examples for all providers |
| `setup.cfg` / `pyproject.toml` | Edit | Add optional extras |
| `CLAUDE.md` | Edit | Update architecture docs |
