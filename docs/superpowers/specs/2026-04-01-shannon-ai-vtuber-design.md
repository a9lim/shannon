# Shannon — AI VTuber Design Spec

An autonomous AI VTuber powered by Claude, with pluggable providers for every subsystem. Shannon can see your screen and webcam, speak via TTS, react through a Live2D VTuber model, and interact with your computer — all driven by a central async event bus.

## Architecture

**Event bus** built on Python `asyncio`. All modules communicate exclusively through typed async events — no module references another directly. Publish/subscribe pattern.

**Six core modules**, each owning a manager (event bus bridge) and one or more pluggable providers:

| Module | Manager | Responsibility |
|--------|---------|----------------|
| Brain | `Brain` | Orchestrates LLM calls, manages conversation context, injects memory |
| Input | `InputManager` | Receives text or speech input, emits `UserInput` events |
| Output | `OutputManager` | Routes LLM responses to TTS and VTuber model |
| Vision | `VisionManager` | Captures screen and/or webcam frames on a configurable interval |
| Actions | `ActionManager` | Executes shell, browser, mouse, and keyboard actions with safety checks |
| Autonomy | `AutonomyLoop` | Background task that decides when Shannon should react unprompted |
| Messaging | `MessagingManager` | Bridges external chat platforms (Discord, etc.) as input/output channels |

## Event System

### Core Event Types

| Event | Published by | Consumed by | Payload |
|-------|-------------|-------------|---------|
| `UserInput` | InputManager | Brain | text, source (text\|voice) |
| `VisionFrame` | VisionManager | Brain, AutonomyLoop | image bytes, source (screen\|cam) |
| `AutonomousTrigger` | AutonomyLoop | Brain | reason, context (vision summary) |
| `LLMResponse` | Brain | OutputManager, ActionManager | text, expressions[], actions[], mood |
| `SpeechStart` | OutputManager | VTuberProvider | audio duration, phonemes |
| `SpeechEnd` | OutputManager | VTuberProvider | (signals mouth close) |
| `ExpressionChange` | OutputManager | VTuberProvider | expression name, intensity |
| `ActionRequest` | Brain | ActionManager | type (shell\|browser\|mouse\|kb), params |
| `ActionResult` | ActionManager | Brain | stdout/stderr, success, screenshot |
| `ConfigChange` | UI / CLI | All managers | key, old_value, new_value |
| `ChatMessage` | MessagingManager | Brain | text, author, platform, channel |
| `ChatResponse` | Brain | MessagingManager | text, channel, reply_to |

### Data Flow: User Message

1. User types or speaks → InputManager emits `UserInput`
2. Brain gathers context: conversation history, latest VisionFrame(s), personality prompt, recalled memories
3. Brain calls LLM provider → receives structured response (text + expressions + actions)
4. Brain emits `LLMResponse`
5. OutputManager routes text to TTS provider, expression data to VTuber provider
6. ActionManager executes any requested actions, emits `ActionResult` back to Brain

### Data Flow: Autonomous Reaction

1. VisionManager emits `VisionFrame` every N seconds
2. AutonomyLoop evaluates: has the screen changed significantly? Has it been quiet too long? Is cooldown elapsed?
3. If triggered, emits `AutonomousTrigger` with reason and context
4. Brain handles it the same as a `UserInput` — gathers context, calls LLM, emits response

## Provider System

Every external dependency is abstracted behind a provider interface (ABC). Providers are selected via `config.yaml` and loaded at startup through a registry.

### Provider Interfaces

**LLMProvider**
- `generate(messages, tools) → Response`
- `stream(messages, tools) → AsyncIterator`
- `supports_vision() → bool`
- `supports_tools() → bool`
- `supports_streaming() → bool`

Initial implementations:
- `ClaudeProvider` — Anthropic SDK, tool_use for structured output, vision support. **Default and primary.**
- `OllamaProvider` — REST API, JSON mode for structured output. Vision depends on model. Falls back to text parsing if model lacks tool use.

**TTSProvider**
- `synthesize(text) → AudioChunk`
- `stream_synthesize(text) → AsyncIterator[AudioChunk]`
- `get_phonemes(text) → Phonemes`

Initial implementation: `PiperProvider` (piper-tts, local).

**STTProvider**
- `transcribe(audio) → str`
- `stream_transcribe(audio_stream) → AsyncIterator[str]`

Initial implementation: `WhisperProvider` (faster-whisper, local).

**VisionProvider**
- `capture_screen() → Image`
- `capture_webcam() → Image`

Initial implementation: `ScreenCapture` (mss) + `WebcamCapture` (opencv). Both independently toggleable.

**VTuberProvider**
- `set_expression(name, intensity)`
- `start_speaking(phonemes?)`
- `stop_speaking()`
- `set_idle_animation(name)`

Initial implementation: `VTubeStudioProvider` — connects via WebSocket to VTube Studio's API.

**ActionProvider**
- `execute(action) → ActionResult`
- `get_capabilities() → list[str]`
- `validate(action) → bool`

Initial implementations (all loaded simultaneously, dispatched by type):
- `ShellAction` — subprocess execution
- `BrowserAction` — Playwright browser automation
- `MouseAction` — pyautogui mouse control
- `KeyboardAction` — pyautogui keyboard control

**MessagingProvider**
- `connect() → None`
- `disconnect() → None`
- `send_message(channel, text, reply_to?) → None`
- `on_message(callback) → None`

Initial implementation: `DiscordProvider` (discord.py). Future: Twitch chat, IRC, etc.

The MessagingManager bridges external chat platforms to the event bus. Incoming messages emit `ChatMessage` events (consumed by Brain just like `UserInput`). When Brain produces a response to a chat message, it emits `ChatResponse`, which the MessagingManager routes back to the correct platform and channel.

**MemoryProvider**
- `save(category, content) → str` (returns memory ID)
- `recall(query, top_k) → list[Memory]`
- `update(memory_id, content)`
- `forget(memory_id)`

Initial implementation: Local markdown files with keyword search. Future: ChromaDB for vector/semantic search.

### Provider Loading

```yaml
# config.yaml
providers:
  llm:
    type: claude
    model: claude-sonnet-4-6-20250514
    max_tokens: 1024
  tts:
    type: piper
    model: en_US-lessac-medium
    rate: 1.0
  stt:
    type: whisper
    model: base.en
    device: auto
  vision:
    screen: true
    webcam: false
    interval_seconds: 5
  vtuber:
    type: vtube_studio
    host: localhost
    port: 8001

autonomy:
  enabled: true
  cooldown_seconds: 30
  triggers:
    - screen_change
    - idle_timeout
  idle_timeout_seconds: 120

personality:
  name: Shannon
  prompt_file: personality.md
```

A registry maps type strings to classes. At startup, each provider is instantiated from config and injected into its manager.

## Memory System

Shannon autonomously manages her own persistent memory.

### How It Works

1. Brain includes memory-management tools in every LLM call: `save_memory`, `recall_memories`, `update_memory`, `forget_memory`
2. Shannon decides when to save — the LLM calls these tools naturally during conversation
3. On each LLM call, Brain does a lightweight recall pass: keyword-extract from current context → pull top-K relevant memories → inject into system prompt as a "What I know" section

### Storage

```
memory/
├── index.md                 # Table of contents
├── conversation_history/    # Rolling conversation log (windowed + summarized)
└── long_term/               # Autonomous persistent memory
    ├── people.md
    ├── preferences.md
    ├── facts.md
    └── ...                  # Shannon creates new files as needed
```

- Conversation windowing: recent messages kept in full, older ones summarized. Configurable window size.
- Memory directory is gitignored — personal data stays local.
- Backend is pluggable via `MemoryProvider` ABC.

## Safety & Action System

### Action Execution Pipeline

Every action goes through five gates:

1. **Type validation** — unknown action type → reject with warning
2. **Enabled check** — disabled in config → reject silently
3. **Provider validation** — provider-specific checks (command blocklists, URL blocklists, rate limits, screen bounds)
4. **Approval check** — configurable per action type (see below)
5. **Execute** — run the action, emit `ActionResult`

### Approval Modes

| Mode | Behavior |
|------|----------|
| `allow` | Execute immediately, no prompt |
| `confirm` | Show the user what Shannon wants to do, wait for y/n in terminal |
| `deny` | Always reject; Shannon is told the action was denied |

**Default: everything is `confirm`.** The user must approve each action.

The `--dangerously-skip-permissions` CLI flag switches all action types to `allow` mode.

### Default Safety Config

```yaml
actions:
  shell:
    enabled: true
    approval: confirm
    blocklist:
      - "rm -rf"
      - "sudo"
      - "shutdown"
      - "reboot"
      - "mkfs"
      - "dd if="
    allowlist: ["*"]
    timeout_seconds: 30
  browser:
    enabled: true
    approval: confirm
    allowed_domains: ["*"]
    blocked_domains: []
    headless: false
  mouse:
    enabled: true
    approval: confirm
    rate_limit: 10
    confined_to_screen: true
  keyboard:
    enabled: true
    approval: confirm
    rate_limit: 20
    blocked_combos:
      - "cmd+q"
      - "alt+f4"
      - "ctrl+alt+delete"
```

### Safety Philosophy

- **Defense in depth** — config toggles → blocklists → provider validation → approval prompts. Multiple layers.
- **Sane defaults** — everything on `confirm`, destructive commands blocklisted, dangerous key combos blocked, mouse/keyboard rate-limited.
- **Transparent** — every action attempt is logged. Shannon is told when actions are denied so she can explain or try alternatives.
- **No silent failures** — denied actions return `ActionResult(success=false, reason=...)` which feeds back to the Brain.

## Personality

Shannon's personality is defined in `personality.md` at the project root — a markdown file containing her system prompt, behavioral guidelines, and character traits. This is loaded by the Brain and injected as the system prompt for every LLM call, alongside recalled memories and conversation context.

## Input Modes

- **Primary: text → text** — user types in terminal, Shannon responds as text (displayed) + expressions (VTuber model)
- **Toggleable: speech → speech** — user speaks via microphone (STT), Shannon responds via TTS + VTuber model
- **Autonomous reactions** — Shannon watches vision inputs and reacts on her own, with configurable cooldowns
- Output mode (TTS vs text popup) is configurable independently of input mode

## Configuration

All configuration lives in `config.yaml`. Key sections:

- `providers` — which implementation to use for each provider type + their settings
- `actions` — safety settings, approval modes, blocklists per action type
- `autonomy` — enable/disable, cooldown, trigger types, idle timeout
- `personality` — name, path to personality.md

## Project Structure

```
shannon/
├── config.yaml
├── personality.md
├── memory/                      # gitignored
│   ├── index.md
│   ├── conversation_history/
│   └── long_term/
│
├── shannon/
│   ├── __init__.py
│   ├── app.py                   # Entry point
│   ├── bus.py                   # Event bus
│   ├── events.py                # Event type definitions
│   ├── config.py                # Config loading
│   │
│   ├── brain/
│   │   ├── __init__.py
│   │   ├── brain.py             # Brain manager
│   │   ├── memory.py            # Memory manager
│   │   ├── prompt.py            # System prompt builder
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── base.py          # LLMProvider ABC
│   │       ├── claude.py
│   │       └── ollama.py
│   │
│   ├── input/
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── base.py          # STTProvider ABC
│   │       ├── text.py
│   │       └── whisper.py
│   │
│   ├── output/
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── providers/
│   │       ├── tts/
│   │       │   ├── base.py      # TTSProvider ABC
│   │       │   └── piper.py
│   │       └── vtuber/
│   │           ├── base.py      # VTuberProvider ABC
│   │           └── vtube_studio.py
│   │
│   ├── vision/
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── providers/
│   │       ├── base.py          # VisionProvider ABC
│   │       ├── screen.py
│   │       └── webcam.py
│   │
│   ├── actions/
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── providers/
│   │       ├── base.py          # ActionProvider ABC
│   │       ├── shell.py
│   │       ├── browser.py
│   │       ├── mouse.py
│   │       └── keyboard.py
│   │
│   ├── autonomy/
│   │   ├── __init__.py
│   │   └── loop.py
│   │
│   └── messaging/
│       ├── __init__.py
│       ├── manager.py
│       └── providers/
│           ├── base.py          # MessagingProvider ABC
│           └── discord.py       # discord.py
│
└── tests/
    ├── test_bus.py
    ├── test_brain.py
    ├── test_memory.py
    └── ...
```

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client |
| `piper-tts` | Local TTS |
| `faster-whisper` | Local STT |
| `mss` | Screen capture |
| `opencv-python` | Webcam capture |
| `pyautogui` | Mouse and keyboard control |
| `playwright` | Browser automation |
| `websockets` | VTube Studio API connection |
| `discord.py` | Discord bot client |
| `pyyaml` | Config loading |
