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

**Message flow:** Transport receives message → constructs `IncomingMessage` → publishes `MessageIncoming` to EventBus → `MessageHandler.handle()` in `core/pipeline.py` → rate limit check → command dispatch (`core/commands.py`) → auth check → load context from SQLite → build system prompt with tools filtered by user permission → `ToolExecutor.run()` in `core/tool_executor.py` (LLM + tool-use loop, up to 10 iterations) → store response → publish `MessageOutgoing` with `OutgoingMessage` → Transport delivers with chunking.

**Key modules:**
- `models.py` — Typed `IncomingMessage` and `OutgoingMessage` dataclasses (replace untyped event dicts)
- `core/bus.py` — `EventBus` with typed pub/sub, per-subscriber queues; events carry typed `message` fields
- `core/llm/` — LLM subpackage: `types.py` (LLMMessage, ToolCall, LLMResponse), `base.py` (LLMProvider ABC), `anthropic.py` (AnthropicProvider), `local.py` (LocalProvider + ReAct), `__init__.py` (re-exports + `create_provider` factory)
- `core/pipeline.py` — `MessageHandler`: full message handling pipeline (rate limit → command → auth → context → LLM → response)
- `core/tool_executor.py` — `ToolExecutor`: LLM completion with iterative tool-use loop
- `core/commands.py` — `CommandHandler`: slash command dispatch (/forget, /context, /summarize, /jobs, /sudo, /help)
- `core/context.py` — SQLite-backed per-(platform, channel) conversation history with LLM summarization
- `core/auth.py` — `AuthManager` with `PermissionLevel` IntEnum, rate limiting, sudo escalation
- `core/scheduler.py` — Heartbeat and cron-based task scheduler
- `core/system_prompt.py` — System prompt construction with dynamic tool injection
- `tools/base.py` — `BaseTool` ABC with `name`, `description`, `parameters`, `execute()`, `cleanup()`, `required_permission` (returns `PermissionLevel`)
- `tools/` — `shell`, `browser` (Playwright, lazy-initialized), `claude_code` (CLI delegation), `interactive` (PTY sessions via pexpect/pywinpty)
- `transports/base.py` — `Transport` ABC for messaging platforms
- `transports/discord_transport.py` — Discord transport using discord.py
- `transports/signal_transport.py` — Signal transport with shared `_parse_envelope()` for CLI and REST modes
- `main.py` — `Shannon` class (wiring + lifecycle), `run()`, CLI entry point

**Orchestrator:** `Shannon` class in `main.py` wires bus + auth + LLM + context + scheduler + tools + transports. Pipeline components (`MessageHandler`, `ToolExecutor`, `CommandHandler`) are composed at init.

**Permissions:** `PermissionLevel` IntEnum (PUBLIC=0, TRUSTED=1, OPERATOR=2, ADMIN=3). Tools declare `required_permission` as `PermissionLevel`. `AuthManager` also handles per-user rate limiting and sudo escalation (request → admin approve/deny → temporary elevation with timeout).

**Context:** SQLite-backed per-(platform, channel) conversation history. `get_context(platform, channel)` returns messages. LLM-based summarization when approaching token limit — summarizes oldest half of messages and replaces with summary. Explicit `/summarize` command also available.

## Conventions

- Pure asyncio, no threading (use `asyncio.to_thread()` for blocking ops like pexpect)
- Dataclasses for events, message models, and LLM types; Pydantic models for config
- Config via Pydantic BaseSettings: env vars (`SHANNON_*` prefix, `__` for nesting) override YAML
- structlog for logging with sensitive data filtering; DEBUG level warns at startup
- All components have `start()`/`stop()` lifecycle methods; all tools have `cleanup()` (no-op by default)
- Platform-aware paths via `utils/platform.py` (Windows/macOS/Linux)
- Platform-conditional deps: pexpect on Unix, pywinpty on Windows
- Slash commands dispatched by `CommandHandler` in `core/commands.py`

## Adding New Components

**New tool:** Subclass `BaseTool`, implement `name`, `description`, `parameters`, `execute()`. Set `required_permission` to return a `PermissionLevel`. Override `cleanup()` if resources need teardown. Add instance to `Shannon.tools` list in `main.py`.

**New transport:** Subclass `Transport`, implement `platform_name`, `start()`, `stop()`, `send_message()`. Subscribe to `MESSAGE_OUTGOING` in `start()`, publish `MessageIncoming` events with typed `IncomingMessage` on received messages. Register in `Shannon.start()`.

**New LLM provider:** Subclass `LLMProvider` from `core/llm/base.py`, implement `complete()`, `stream()`, `count_tokens()`. Add to `create_provider()` factory in `core/llm/__init__.py`.
