# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Shannon is an async Python LLM-powered autonomous assistant that communicates over messaging platforms (Discord, Signal), executes system commands, browses the web, delegates tasks to Claude Code, drives interactive CLI programs, and schedules its own work. It uses an event-driven architecture with a central async pub/sub bus.

## Commands

```bash
# Install in editable mode (with dev deps for testing)
pip install -e ".[dev]"

# Run Shannon
python -m shannon.main
python -m shannon.main --config path/to/config.yaml --log-level DEBUG --dry-run

# Run tests
pytest tests/ -v

# Run a single test file
pytest tests/test_chunker.py -v

# Run a single test
pytest tests/test_auth.py::TestSudo::test_approve_sudo -v

# Config: set env vars (SHANNON_LLM__API_KEY, SHANNON_DISCORD__TOKEN)
# or create ~/.shannon/config.yaml from config.example.yaml
```

## Architecture

**Message flow:** Transport receives message → publishes `MessageIncoming` to EventBus → `Shannon._handle_message()` → rate limit check → auth check → load context from SQLite → build system prompt with tools filtered by user permission → call LLM (Anthropic or local) → tool-use loop (up to 10 iterations) → store response → publish `MessageOutgoing` → Transport delivers with chunking.

**Key abstractions (all async):**
- `EventBus` (`core/bus.py`) — typed pub/sub with per-subscriber queues; all components communicate through events, never directly
- `LLMProvider` (`core/llm.py`) — ABC with `complete()`, `stream()`, `count_tokens()`, `close()`. Two implementations: `AnthropicProvider` (native tool use) and `LocalProvider` (OpenAI-compatible endpoints with ReAct fallback for models without tool support). Use `create_provider(config)` factory.
- `Transport` (`transports/base.py`) — ABC for messaging platforms; `DiscordTransport` and `SignalTransport` (signal-cli subprocess or signal-cli-rest-api HTTP modes)
- `BaseTool` (`tools/base.py`) — ABC with `name`, `description`, `parameters` (JSON Schema), `execute()`, `required_permission`. Tools: `shell`, `browser` (Playwright, lazy-initialized), `claude_code` (CLI delegation), `interactive` (PTY sessions via pexpect/pywinpty)

**Orchestrator:** `Shannon` class in `main.py` wires bus + auth + LLM + context + scheduler + tools + transports. The `_llm_with_tools()` method implements the tool-use loop.

**Permissions:** `PermissionLevel` IntEnum (PUBLIC=0, TRUSTED=1, OPERATOR=2, ADMIN=3). Tools declare `required_permission`. `AuthManager` also handles per-user rate limiting and sudo escalation (request → admin approve/deny → temporary elevation with timeout).

**Context:** SQLite-backed per-(platform, channel) conversation history. LLM-based summarization when approaching token limit — summarizes oldest half of messages and replaces with summary. Explicit `/summarize` command also available.

## Conventions

- Pure asyncio, no threading (use `asyncio.to_thread()` for blocking ops like pexpect)
- Dataclasses for events and LLM types; Pydantic models for config
- Config via Pydantic BaseSettings: env vars (`SHANNON_*` prefix, `__` for nesting) override YAML
- structlog for logging with sensitive data filtering; DEBUG level warns at startup
- All components have `start()`/`stop()` lifecycle methods; tools with resources have `cleanup()`
- Platform-aware paths via `utils/platform.py` (Windows/macOS/Linux)
- Platform-conditional deps: pexpect on Unix, pywinpty on Windows
- Slash commands (`/forget`, `/context`, `/summarize`, `/jobs`, `/sudo`, `/help`) handled in `_handle_command()`

## Adding New Components

**New tool:** Subclass `BaseTool`, implement `name`, `description`, `parameters`, `execute()`. Add instance to `Shannon.tools` list in `main.py`. Add optional `cleanup()` for resource teardown.

**New transport:** Subclass `Transport`, implement `platform_name`, `start()`, `stop()`, `send_message()`. Subscribe to `MESSAGE_OUTGOING` in `start()`, publish `MessageIncoming` events on received messages. Register in `Shannon.start()`.

**New LLM provider:** Subclass `LLMProvider`, implement `complete()`, `stream()`, `count_tokens()`. Add to `create_provider()` factory in `core/llm.py`.
