# Shannon

AI VTuber powered by Claude. Async event bus architecture with direct Anthropic SDK integration.

## Quick Start

```bash
pip install -e ".[dev]"           # Core + test deps
pip install -e ".[all,dev]"       # All optional providers
python3 -m pytest tests/ -v       # Run tests (451 tests, ~32s)
shannon                           # Run (needs API key in config.yaml or ANTHROPIC_API_KEY env var)
shannon --speech                  # Speech I/O mode
shannon --dangerously-skip-permissions  # Skip tool confirmation prompts
```

## Architecture

All modules communicate through a central async `EventBus` (pub/sub, `shannon/bus.py`). No module references another directly — they publish and subscribe to typed events defined in `shannon/events.py`.

**Modules:** Brain, Input, Output, Vision, Autonomy, Messaging — each wired directly in `app.py`. The Brain uses the Anthropic SDK directly via `ClaudeClient`; there is no LLM provider abstraction.

## Key Patterns

- **Brain decomposed** into `brain.py` (orchestration), `claude.py` (API client), `tool_dispatch.py` (executor routing), `tool_registry.py` (tool list builder).
- **Config** is nested dataclasses in `shannon/config.py`, loaded from `config.yaml` with `_merge_dataclass()` for partial overrides. `_merge_dataclass` performs type coercion (scalar→list, string→int/float), warns on unknown keys, and recursively visits all nested dataclass fields (even those absent from the YAML) to ensure `__post_init__` validators always run. Config values are validated via `__post_init__` (clamping, range checks) — automatically re-run after merge. `_build_defaults()` uses a `_SKIP_VALIDATION` flag to construct defaults without triggering validation, which runs after YAML merge. Missing API key or missing Discord token (when enabled) raise `ValueError` at startup.
- **Anthropic native tools** — server-side tools (`web_search`, `web_fetch`, `code_execution`, `memory`) are declared in the tools list and handled by the API. Client-side tools (`computer`, `bash`, `str_replace_based_edit_tool`) are executed locally by tool executors in `shannon/tools/` and `shannon/computer/`.
- **No ActionManager** — tool calls from the LLM are dispatched directly by `ToolDispatcher`. Confirmation is handled via the event bus: `ToolDispatcher` publishes `ToolConfirmationRequest`, a handler (CLI stdin by default) prompts the user and publishes `ToolConfirmationResponse`. Controlled by `require_confirmation` flags in each tool's config (default `True`). `--dangerously-skip-permissions` sets all flags to `False`.
- **Memory** uses the `memory` tool (type `memory_20250818`) — despite the Anthropic-hosted type name, this is a **client-side** tool. The API returns `tool_use` blocks that require `tool_result` responses. `MemoryBackend` (`shannon/tools/memory_backend.py`) executes file operations (view, create, str_replace, insert, delete, rename) against a local directory (`config.memory.dir`/memories/).
- Optional deps are lazy-imported with `try/except ImportError` — missing deps degrade gracefully with a warning.

## Anthropic API Features

- **Adaptive thinking** — enabled via `llm.thinking: true` in config (extended thinking for complex tasks)
- **Streaming** — `ClaudeClient` streams responses for low-latency output
- **Prompt caching** — system prompt cached with `cache_control: ephemeral`
- **Compaction** — conversation history compacted via `compact-2026-01-12` beta header when `llm.compaction: true`
- **1M context** — `context-1m-2025-08-07` beta header included when `llm.enable_1m_context: true` (default)
- **Message normalization** — `ClaudeClient._normalize_messages()` merges consecutive same-role messages to ensure strict user/assistant alternation (but never merges messages containing `tool_use` or `tool_result` blocks, to preserve pairing integrity; also skips merging when both messages have empty content to avoid API errors)
- **Tool rate limits** — `web_search` and `web_fetch` have `max_uses: 3` to prevent runaway API costs

## Tool Set

9 tools total:

| Tool | Type | Side |
|---|---|---|
| `computer` | `computer_20251124` | client (conditional) |
| `bash` | `bash_20250124` | client (conditional) |
| `str_replace_based_edit_tool` | `text_editor_20250728` | client (conditional) |
| `code_execution` | `code_execution_20260120` | server |
| `memory` | `memory_20250818` | client |
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

- **Token efficiency** — custom emoji context is only injected when `reaction_probability > 0`. Dynamic context (emoji, participants) is stripped from history entries to avoid compounding token waste. Images are cleared from messages after the first LLM call in a tool loop to prevent re-transmission.

Config fields: `messaging.debounce_delay` (0-60, default 3.0), `messaging.reply_probability` (0-1, default 0.0), `messaging.reaction_probability` (0-1, default 0.0), `messaging.conversation_expiry` (0-3600, default 300.0), `messaging.max_context_messages` (>=0, default 20), `messaging.admin_ids` (list of Discord user ID strings, default []).

## Continue (Multi-Message) System

The LLM can call the `continue` tool to send multiple messages in a row without waiting for user input. Each call emits the current text immediately, then the brain calls the LLM again. Capped at `memory.max_continues` (default 5). The continue tool is handled entirely client-side — no `tool_result` is sent back to the API. For chat platforms, the first message replies to the original; follow-ups are standalone messages in the channel.

When the tool loop exhausts its maximum iterations without completing, the brain makes a final tool-free LLM call to produce a coherent closing response.

## Discord Voice Channels

Shannon can join Discord voice channels for full-duplex audio communication. Requires `--speech` flag and `messaging.voice.enabled: true`.

**How it works:** VoiceManager auto-joins configured voice channels when users enter, captures per-user audio via raw UDP socket listener (RTP parse → transport decrypt → DAVE E2EE decrypt → opus decode → PCM buffer), batches on silence gaps, transcribes via Whisper STT, and sends the combined input to the brain. Responses are synthesized via the configured TTS provider and played back through the VoiceClient.

**TTS providers:** Configured via `tts.type` in config. Two backends:
- **Piper** (`tts.type: piper`) — lightweight, CPU-friendly, preset voices. Install with `pip install 'shannon[tts]'`. Auto-detects pinyin models for cross-language synthesis.
- **Coqui** (`tts.type: coqui`) — higher quality, more voices, heavier (GPU recommended). Install with `pip install 'shannon[coqui]'`. Supports multi-speaker models via `tts.speaker` config field (e.g., `tts.speaker: p225` for VCTK). No streaming API — synthesizes full text then yields.

Config fields: `tts.type` ("piper" or "coqui"), `tts.model` (model path for Piper, model name like `tts_models/en/ljspeech/tacotron2-DDC` for Coqui), `tts.speaker` (multi-speaker model speaker ID, Coqui only), `tts.rate` (speech rate, Piper only).

**Cross-language TTS:** `PiperProvider` auto-detects pinyin-type models (e.g., `zh_CN-xiao_ya-medium`) and routes English text through `en_to_pinyin.py` instead of the Chinese G2P. Pipeline: espeak-ng IPA → approximate pinyin phonemes → custom `pinyin_to_ids` (English-tuned padding) → `phoneme_ids_to_audio`. Key design decisions in the converter:
- **Vowel mapping**: pinyin `e` = [ɤ] (not schwa), so IPA `ə` maps to `a` (stressed/after h) or `e` (unstressed, consonant-dependent). Labial onsets (b/p/m/f) use `u` for schwa since `be`/`pe`/`fe` are invalid pinyin.
- **Consonant codas**: Mandarin only allows -n/-ng codas. Stops always drop ("had"→ha). Sibilants always keep as syllabic (si5≈[s]). Others (f, etc.) keep only in stressed syllables. Coda `l` vocalizes to `ou` (dark L ≈ [ʊ]), coda `ɹ` produces an `er` syllable.
- **Palatalization**: s→x, z→j, sh→x, zh→j, ch→q before true [i] finals (not epenthetic si5/zi5).
- **Onset clusters**: epenthetic vowel borrows from next semivowel (k before w→ku, t before w→tu). Sibilants get `i`, labials get `u`, others get `e`.
- **Timing**: tone 5 (neutral) for unstressed syllables (shorter in model). Custom `pinyin_to_ids` pads only after tones and real punctuation, not spaces — words flow together within phrases.

**Decryption chain:** Transport layer (XSalsa20-Poly1305 legacy or AEAD-AES256-GCM modern, auto-detected from negotiated mode) → DAVE E2EE layer (via `davey.DaveSession.decrypt`, transparent passthrough when DAVE is not active). Thread-safe: socket reader thread accesses shared buffers, opus decoder, and SSRC-to-user mappings under a `threading.Lock`. The mute-during-playback flag uses `threading.Event` for atomic cross-thread signaling.

**Config fields:** `messaging.voice.enabled` (default false), `messaging.voice.auto_join_channels` (list of channel IDs, empty = any), `messaging.voice.silence_threshold` (0.5-10.0, default 2.0), `messaging.voice.buffer_max_seconds` (5.0-60.0, default 30.0), `messaging.voice.voice_reply_probability` (0-1, default 1.0), `messaging.voice.mute_during_playback` (default true), `messaging.voice.volume` (0-2, default 1.0).

**Dependencies:** `PyNaCl`, `davey`, `audioop-lts` (for Python 3.13+), system `libopus`. Install with `pip install 'shannon[voice]'`. AES-GCM mode also requires `cryptography` (usually already installed).

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
│   └── text_editor_executor.py
├── computer/           # Computer-use tool executor
│   ├── executor.py     # ComputerUseExecutor (pyautogui)
│   └── screenshot.py
├── input/              # InputManager + STTProvider (text.py, whisper.py)
├── output/             # OutputManager + TTSProvider (piper.py, coqui.py, en_to_pinyin.py) + VTuberProvider (vtube_studio.py)
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

Python from python.org may fail SSL verification (e.g., Discord connections). The app uses `truststore` to inject the macOS system cert store — install it with `pip install 'shannon[macos]'`.

## Autonomy & Rate Limits

The autonomy loop fires LLM requests on idle timeout and screen changes. Each trigger type has its own independent cooldown timer — firing `idle_timeout` does not suppress `screen_change` or vice versa. Vision captures 1 frame per minute; the brain keeps only the latest frame. Tune `autonomy.cooldown_seconds` and `vision.interval_seconds` in `config.yaml` to control API usage.

## Adding a New Tool

To add a client-side tool:

1. Create an executor in `shannon/tools/your_executor.py` with an async `execute(params) -> str | dict` method
2. Register it in `ToolDispatcher.__init__` and add a dispatch branch in `ToolDispatcher.dispatch`
3. Add the tool definition to `ToolRegistry._build()` (user-defined format with `input_schema`, or Anthropic-hosted format with `type`) — tools are cached at init
4. Add config fields to the relevant dataclass in `shannon/config.py` if needed
5. Wire the executor in `app.py` (follow existing pattern with `try/except ImportError` for optional deps)
6. Add optional dependency group in `pyproject.toml` if new deps are required

To add a server-side tool: just add `{"type": "tool_type_string", "name": "tool_name"}` to `ToolRegistry._build()` and add the name to `_SERVER_SIDE_TOOLS` in `tool_dispatch.py` — no executor needed.
