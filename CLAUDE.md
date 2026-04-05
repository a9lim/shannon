# Shannon

AI VTuber powered by Claude. Async event bus architecture with direct Anthropic SDK integration.

## Quick Start

```bash
pip install -e ".[dev]"           # Core + test deps
pip install -e ".[all,dev]"       # All optional providers
python3 -m pytest tests/ -v       # Run tests (396 tests, ~29s)
shannon                           # Run (needs API key in config.yaml or ANTHROPIC_API_KEY env var)
shannon --speech                  # Speech I/O mode
shannon --dangerously-skip-permissions  # Skip tool confirmation prompts
```

## Architecture

All modules communicate through a central async `EventBus` (pub/sub, `shannon/bus.py`). No module references another directly — they publish and subscribe to typed events defined in `shannon/events.py`.

**Modules:** Brain, Input, Output, Vision, Autonomy, Messaging — each wired directly in `app.py`. The Brain uses the Anthropic SDK directly via `ClaudeClient`; there is no LLM provider abstraction.

## Key Patterns

- **Brain decomposed** into `brain.py` (orchestration), `claude.py` (API client), `tool_dispatch.py` (executor routing), `tool_registry.py` (tool list builder).
- **Config** is nested dataclasses in `shannon/config.py`, loaded from `config.yaml` with `_merge_dataclass()` for partial overrides. `_merge_dataclass` performs type coercion (scalar→list, string→int/float) and warns on unknown keys. Config values are validated via `__post_init__` (clamping, range checks) — automatically re-run after merge. `_build_defaults()` uses a `_SKIP_VALIDATION` flag to construct defaults without triggering validation, which runs after YAML merge. Missing API key or missing Discord token (when enabled) raise `ValueError` at startup.
- **Anthropic native tools** — server-side tools (`web_search`, `web_fetch`, `code_execution`, `memory`) are declared in the tools list and handled by the API. Client-side tools (`computer`, `bash`, `str_replace_based_edit_tool`) are executed locally by tool executors in `shannon/tools/` and `shannon/computer/`.
- **No ActionManager** — tool calls from the LLM are dispatched directly by `ToolDispatcher`. Confirmation is handled via the event bus: `ToolDispatcher` publishes `ToolConfirmationRequest`, a handler (CLI stdin by default) prompts the user and publishes `ToolConfirmationResponse`. Controlled by `require_confirmation` flags in each tool's config (default `True`). `--dangerously-skip-permissions` sets all flags to `False`.
- **Memory** uses the Anthropic-hosted `memory` tool (type `memory_20250818`) — the API manages recall automatically. The client-side `MemoryBackend` validates paths with URL-decode + `..` fast-reject + symlink-resolved containment check against `_memories_root` (not the broader `base_dir`).
- Optional deps are lazy-imported with `try/except ImportError` — missing deps degrade gracefully with a warning.

## Anthropic API Features

- **Adaptive thinking** — enabled via `llm.thinking: true` in config (extended thinking for complex tasks)
- **Streaming** — `ClaudeClient` streams responses for low-latency output
- **Prompt caching** — system prompt cached with `cache_control: ephemeral`
- **Compaction** — conversation history compacted via `compact-2026-01-12` beta header when `llm.compaction: true`
- **1M context** — `context-1m-2025-08-07` beta header always included
- **Message normalization** — `ClaudeClient._normalize_messages()` merges consecutive same-role messages to ensure strict user/assistant alternation (but never merges messages containing `tool_use` or `tool_result` blocks, to preserve pairing integrity)
- **Tool rate limits** — `web_search` and `web_fetch` have `max_uses: 3` to prevent runaway API costs

## Tool Set

9 tools total:

| Tool | Type | Side |
|---|---|---|
| `computer` | `computer_20251124` | client (conditional) |
| `bash` | `bash_20250124` | client (conditional) |
| `str_replace_based_edit_tool` | `text_editor_20250728` | client (conditional) |
| `code_execution` | `code_execution_20260120` | server |
| `memory` | `memory_20250818` | server |
| `web_search` | `web_search_20260209` | server |
| `web_fetch` | `web_fetch_20260209` | server |
| `set_expression` | user-defined | client |
| `continue` | user-defined | client |

Conditional tools (`computer`, `bash`, `str_replace_based_edit_tool`) are enabled/disabled via `tools.*` in config.

## Event Flow

`UserInput` / `ChatMessage` → **Brain** (assembles context + history → calls Claude) → `LLMResponse` → **OutputManager** (TTS or print) + `ExpressionChange` → **VTuber**

Tool calls are dispatched inline during the LLM turn. Confirmation requests go through the event bus (`ToolConfirmationRequest` → handler → `ToolConfirmationResponse`) but the tool result is returned inline to the LLM loop.

Messaging: **DiscordProvider** → **MessagingManager** (debounce, should_respond check) → `ChatMessage` → **Brain** → `ChatResponse` (with reactions) → **MessagingManager** → **DiscordProvider** (split messages, apply reactions)

Autonomous: **VisionManager** emits `VisionFrame` → **AutonomyLoop** evaluates triggers → `AutonomousTrigger` → **Brain** (same flow)

Voice: **User speaks in VC** → VoiceManager captures per-user audio → silence gap → Whisper STT → `VoiceInput` → **Brain** → `LLMResponse` (CLI) + `VoiceOutput` → **VoiceManager** plays TTS in VC

## Messaging Behavior

`MessagingManager` adds platform-agnostic chat behaviors on top of the event bus:

- **Debounce** — per-channel, configurable delay (`messaging.debounce_delay`). New messages cancel pending responses. Typing indicator shown during debounce and before each response delivery.
- **Response eligibility** — responds to @mentions, replies to bot, active conversations (within `messaging.conversation_expiry`), or random chance (`messaging.reply_probability`).
- **Conversation continuity** — detects active conversations by checking recent Discord channel history for bot replies within the expiry window. Survives restarts.
- **Reactions** — LLM can include `[react: emoji]` markers in output. Brain extracts them via `extract_reactions()` and puts them in `ChatResponse.reactions`. Provider applies them. Empty LLM responses emit a ⚠️ reaction as a fail-safe.
- **Custom emoji** — `DiscordProvider` collects available guild emoji and injects them into the system prompt so the LLM knows what custom emoji are available.
- **Participant tracking** — message author info (ID → display name) is passed to the brain and included in the system prompt. Admin users (configured via `messaging.admin_ids`) are annotated.
- **Attachments** — images sent to Discord are downloaded and passed to the brain as vision input. Text files are inlined into the message. Other files are annotated.
- **Message splitting** — responses over 2000 chars are split at newlines, then sentence boundaries (`. `, `! `, `? `), then spaces, then hard boundaries.
- **Bot filtering** — messages from all bots are ignored, not just self.

Config fields: `messaging.debounce_delay` (0-60, default 3.0), `messaging.reply_probability` (0-1, default 0.0), `messaging.reaction_probability` (0-1, default 0.0), `messaging.conversation_expiry` (0-3600, default 300.0), `messaging.max_context_messages` (>=0, default 20), `messaging.admin_ids` (list of Discord user ID strings, default []).

## Continue (Multi-Message) System

The LLM can call the `continue` tool to send multiple messages in a row without waiting for user input. Each call emits the current text immediately, then the brain calls the LLM again. Capped at `memory.max_continues` (default 5). For chat platforms, the first message replies to the original; follow-ups are standalone messages in the channel.

When the tool loop exhausts its maximum iterations without completing, the brain makes a final tool-free LLM call to produce a coherent closing response.

## Discord Voice Channels

Shannon can join Discord voice channels for full-duplex audio communication. Requires `--speech` flag and `messaging.voice.enabled: true`.

**How it works:** VoiceManager auto-joins configured voice channels when users enter, captures per-user audio via raw UDP socket listener (RTP parse, decrypt, opus decode, PCM buffer), batches on silence gaps, transcribes via Whisper STT, and sends the combined input to the brain. Responses are synthesized via Piper TTS and played back through the VoiceClient.

**Config fields:** `messaging.voice.enabled` (default false), `messaging.voice.auto_join_channels` (list of channel IDs, empty = any), `messaging.voice.silence_threshold` (0.5-10.0, default 2.0), `messaging.voice.buffer_max_seconds` (5.0-60.0, default 30.0), `messaging.voice.voice_reply_probability` (0-1, default 1.0), `messaging.voice.mute_during_playback` (default true), `messaging.voice.volume` (0-2, default 1.0).

**Dependencies:** `PyNaCl`, `davey`, system `libopus`. Install with `pip install 'shannon[voice]'`.

## Testing

```bash
python3 -m pytest tests/ -v              # Full suite
python3 -m pytest tests/test_brain.py    # Single module
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. No real API calls — Brain tests mock `ClaudeClient`. Tool dispatch tests that need to bypass confirmation construct `ToolDispatcher` without `tools_config`/`bus` (confirmation disabled when either is `None`). A `conftest.py` autouse fixture sets `ANTHROPIC_API_KEY` so config validation doesn't raise during tests.

## Project Layout

```
shannon/
├── app.py              # Entry point, CLI args, module wiring
├── bus.py              # EventBus (async pub/sub)
├── events.py           # All event dataclasses
├── config.py           # Config dataclasses + YAML loading
├── brain/              # LLM orchestration
│   ├── brain.py        # Central manager — history, context, continue loop
│   ├── claude.py       # ClaudeClient — Anthropic SDK, streaming, caching, compaction
│   ├── tool_dispatch.py  # ToolDispatcher — routes tool calls to executors
│   ├── tool_registry.py  # ToolRegistry — builds tools list + beta headers
│   ├── prompt.py       # System prompt builder
│   ├── reactions.py    # Reaction extraction from LLM output ([react: emoji] markers)
│   └── types.py        # LLMMessage, LLMToolCall (frozen), LLMResponse (frozen)
├── tools/              # Client-side tool executors
│   ├── bash_executor.py
│   ├── text_editor_executor.py
│   └── memory_backend.py
├── computer/           # Computer-use tool executor
│   ├── executor.py     # ComputerUseExecutor (pyautogui)
│   └── screenshot.py
├── input/              # InputManager + STTProvider (text.py, whisper.py)
├── output/             # OutputManager + TTSProvider (piper.py) + VTuberProvider (vtube_studio.py)
├── vision/             # VisionManager + VisionProvider (screen.py, webcam.py)
├── autonomy/           # AutonomyLoop (idle timeout, screen change triggers)
└── messaging/          # MessagingManager + MessagingProvider (discord.py, discord_voice.py)
```

## Credentials

All credentials can be set in `config.yaml`:
- `llm.api_key` — Anthropic API key (falls back to `ANTHROPIC_API_KEY` env var if empty)
- `messaging.token` — Discord bot token (requires `message_content` privileged intent in Developer Portal)
- `vtuber.auth_token` — VTube Studio auth token (optional; first launch prompts approval in VTS)

## SSL on macOS

Python from python.org may fail SSL verification (e.g., Discord connections). The app uses `truststore` to inject the macOS system cert store — install it with `pip install truststore`.

## Autonomy & Rate Limits

The autonomy loop fires LLM requests on idle timeout and screen changes. Vision captures 1 frame per minute; the brain keeps only the latest frame. Tune `autonomy.cooldown_seconds` and `vision.interval_seconds` in `config.yaml` to control API usage.

## Adding a New Tool

To add a client-side tool:

1. Create an executor in `shannon/tools/your_executor.py` with an async `execute(params) -> str | dict` method
2. Register it in `ToolDispatcher.__init__` and add a dispatch branch in `ToolDispatcher.dispatch`
3. Add the tool definition to `ToolRegistry.build()` (user-defined format with `input_schema`, or Anthropic-hosted format with `type`)
4. Add config fields to the relevant dataclass in `shannon/config.py` if needed
5. Wire the executor in `app.py` (follow existing pattern with `try/except ImportError` for optional deps)
6. Add optional dependency group in `pyproject.toml` if new deps are required

To add a server-side tool: just add `{"type": "tool_type_string", "name": "tool_name"}` to `ToolRegistry.build()` — no executor needed.
