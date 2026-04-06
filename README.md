# Shannon

AI VTuber powered by Claude. Async event bus architecture with direct Anthropic SDK integration.

## Setup

Requires Python 3.11+.

```bash
pip install -e "."                # Core only
pip install -e ".[all]"           # All optional providers
pip install -e ".[dev]"           # With test deps
```

### Configuration

Copy the example and fill in your credentials:

```bash
cp config.example.yaml config.yaml
```

```yaml
llm:
  api_key: "sk-ant-..."      # or set ANTHROPIC_API_KEY env var

messaging:
  enabled: true
  token: "your-discord-bot-token"
  admin_ids: ["123456789"]    # Discord user IDs
```

The app will refuse to start without a valid API key. Discord token is required when `messaging.enabled` is true.

### Discord Bot

1. Create a bot at [discord.com/developers](https://discord.com/developers/applications)
2. Enable the **Message Content** privileged intent
3. Invite with `bot` scope and `Send Messages`, `Add Reactions`, `Read Message History` permissions
4. Set the token in `config.yaml` or as an environment variable

## Usage

```bash
shannon                                # Text mode (needs API key)
shannon --speech                       # Speech I/O mode
shannon --dangerously-skip-permissions # Skip tool confirmation prompts
```

## Architecture

All modules communicate through a central async `EventBus` (pub/sub). No module references another directly.

```
UserInput / ChatMessage
        |
      Brain (assembles context → calls Claude → dispatches tools)
        |
   LLMResponse ──→ OutputManager (TTS or print)
        |              |
   ChatResponse    ExpressionChange ──→ VTuber
        |
   MessagingManager ──→ DiscordProvider
```

### Modules

| Module | Purpose |
|--------|---------|
| **Brain** | LLM orchestration, tool dispatch, history, continue loop |
| **Input** | Text or speech input via STT |
| **Output** | TTS, VTuber expression control |
| **Vision** | Screen/webcam capture at configurable intervals |
| **Autonomy** | Idle timeout and screen-change triggers |
| **Messaging** | Discord integration with debounce, conversation detection, reactions |

### Tools

9 tools available to the LLM:

| Tool | Side | Notes |
|------|------|-------|
| `web_search` | server | Rate limited (3 uses/turn) |
| `web_fetch` | server | Rate limited (3 uses/turn) |
| `code_execution` | server | |
| `memory` | server | Anthropic-hosted persistent memory |
| `computer` | client | Screen interaction via pyautogui |
| `bash` | client | Persistent shell with blocklist |
| `str_replace_based_edit_tool` | client | File editing |
| `set_expression` | client | VTuber expression changes |
| `continue` | client | Multi-message responses |

Client-side tools (`computer`, `bash`, `str_replace_based_edit_tool`) require confirmation by default. Disable with `--dangerously-skip-permissions`.

## Messaging Features

- **Debounce** per channel with typing indicators
- **Conversation detection** via Discord message history (survives restarts)
- **Custom emoji** awareness injected into system prompt
- **Participant tracking** with admin annotation
- **Reactions** via `[react: emoji]` markers in LLM output
- **Message splitting** at sentence boundaries for natural chunking
- **Image/file attachments** passed to the LLM as vision input or inlined text

## Configuration Reference

All fields have sensible defaults. Only `llm.api_key` (or `ANTHROPIC_API_KEY` env var) is required.

<details>
<summary>Full config.yaml reference</summary>

```yaml
llm:
  model: claude-opus-4-6
  max_tokens: 16000
  thinking: true              # Adaptive extended thinking
  compaction: true            # Server-side context compaction
  enable_1m_context: true     # 1M token context window
  api_key: ""                 # Falls back to ANTHROPIC_API_KEY env var

tools:
  computer_use:
    enabled: true
    require_confirmation: true
  bash:
    enabled: true
    require_confirmation: true
    blocklist: ["rm -rf", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
    timeout_seconds: 30
  text_editor:
    enabled: true
    require_confirmation: true

tts:
  type: piper                 # "piper" or "coqui"
  model: en_US-lessac-medium
  rate: 1.0
  speaker: ""                 # Multi-speaker model speaker ID (Coqui only)

stt:
  type: whisper
  model: base.en
  device: auto

vision:
  screen: true
  webcam: false
  interval_seconds: 60.0
  max_width: 1024
  max_height: 768

vtuber:
  type: vtube_studio
  host: localhost
  port: 8001
  auth_token: ""

messaging:
  type: discord
  enabled: false
  token: ""
  debounce_delay: 3.0           # 0-60 seconds
  reply_probability: 0.0        # 0-1, chance to reply unprompted
  reaction_probability: 0.0     # 0-1, chance to react
  conversation_expiry: 300.0    # 0-3600 seconds
  max_context_messages: 20
  admin_ids: []                 # Discord user ID strings
  voice:
    enabled: false
    auto_join_channels: []      # Channel IDs, empty = any
    silence_threshold: 2.0      # 0.5-10.0 seconds
    buffer_max_seconds: 30.0    # 5.0-60.0 seconds
    voice_reply_probability: 1.0  # 0-1
    mute_during_playback: true
    volume: 1.0                 # 0-2

autonomy:
  enabled: true
  cooldown_seconds: 30
  triggers: [screen_change, idle_timeout]
  idle_timeout_seconds: 120

personality:
  name: Shannon
  prompt_file: personality.md

memory:
  dir: memory
  conversation_window: 50
  max_session_messages: 40
  recall_top_k: 5
  max_continues: 5
```

</details>

## Testing

```bash
python3 -m pytest tests/ -v       # 478 tests, ~29s
python3 -m pytest tests/test_brain.py  # Single module
```

No real API calls. Brain tests use mock clients. A `conftest.py` fixture provides a dummy API key.

## Project Layout

```
shannon/
├── app.py                  # Entry point, CLI args, module wiring
├── bus.py                  # EventBus (async pub/sub)
├── events.py               # Typed event dataclasses
├── config.py               # Config dataclasses + YAML loading
├── brain/                  # LLM orchestration
│   ├── brain.py            # History, context, tool loop, continue
│   ├── claude.py           # Anthropic SDK client
│   ├── tool_dispatch.py    # Routes tool calls to executors
│   ├── tool_registry.py    # Builds tools list + beta headers
│   ├── prompt.py           # System prompt builder
│   ├── reactions.py        # [react: emoji] extraction
│   └── types.py            # LLMMessage, LLMToolCall, LLMResponse
├── tools/                  # Client-side tool executors
├── computer/               # Computer-use executor (pyautogui)
├── input/                  # Text + Whisper STT
├── output/                 # TTS (Piper/Coqui) + VTuber (VTube Studio)
├── vision/                 # Screen + webcam capture
├── autonomy/               # Idle timeout, screen change triggers
└── messaging/              # Discord provider + manager
```

## License

MIT
