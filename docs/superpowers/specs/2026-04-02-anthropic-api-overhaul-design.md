# Anthropic API Overhaul — Design Spec

Replace Shannon's entire LLM and tool layer with the Anthropic API exclusively. No local model support. Claude is the only provider, using all native Anthropic tools and API features (adaptive thinking, streaming, prompt caching, compaction, 1M context).

## Tool Set

Nine tools. All Anthropic-provided tools use their native type strings. Client-side tools are executed locally by Shannon; server-side tools run on Anthropic's infrastructure.

| Tool | Type String | Execution |
|---|---|---|
| `computer` | `computer_20251124` | Client-side, self-hosted (local pyautogui + mss) |
| `bash` | `bash_20250124` | Client-side, local persistent shell session |
| `str_replace_based_edit_tool` | `text_editor_20250728` | Client-side, local file operations |
| `code_execution` | `code_execution_20260120` | Server-side (Anthropic sandbox) |
| `memory` | `memory_20250818` | Client-side, local file storage |
| `web_search` | `web_search_20260209` | Server-side (Anthropic) |
| `web_fetch` | `web_fetch_20260209` | Server-side (Anthropic) |
| `set_expression` | User-defined | Local VTuber event |
| `continue` | User-defined | Brain loop signal |

### Beta Headers

Passed via `betas` parameter on every API call:
- `computer-use-2025-11-24` — computer use
- `compact-2026-01-12` — server-side compaction
- `context-1m-2025-08-07` — 1M context window

### Tool Declaration

```python
tools = [
    {
        "type": "computer_20251124",
        "name": "computer",
        "display_width_px": config.tools.computer.display_width,
        "display_height_px": config.tools.computer.display_height,
    },
    {"type": "bash_20250124", "name": "bash"},
    {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
    {"type": "code_execution_20260120", "name": "code_execution"},
    {"type": "memory_20250818", "name": "memory"},
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
    {"name": "set_expression", "description": "...", "input_schema": {...}},
    {"name": "continue", "description": "...", "input_schema": {...}},
]
```

## Anthropic API Features

### Adaptive Thinking

`thinking: {"type": "adaptive"}` enabled by default. Claude dynamically decides when and how deeply to think. No `budget_tokens` (deprecated on Opus 4.6 / Sonnet 4.6).

### Streaming

Use `client.beta.messages.stream()` + `.get_final_message()` instead of blocking `client.beta.messages.create()`. Prevents HTTP timeouts on tool-use loops. The provider's `generate()` method returns `LLMResponse` as before — streaming is an implementation detail.

### Prompt Caching

System prompt is stable within a session. Use `cache_control: {"type": "ephemeral"}` on the system prompt block. Tools render before system in the cache key, so caching system also caches the tool definitions.

```python
kwargs["system"] = [
    {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
]
```

~90% cost reduction on system prompt + tools after the first request.

### Compaction

Server-side compaction replaces manual history trimming. The API automatically summarizes older context when approaching the context limit. Critical: append `response.content` (not just extracted text) to messages each turn — compaction blocks must be preserved.

### 1M Context Window

Enabled via beta header. Essential for long conversations with many tool results (screenshots, file contents, web search results).

### Max Tokens

Default 16000 (streaming makes higher values safe). Current 1024 default is far too low for tool-use flows.

## What Gets Deleted

| Item | Reason |
|---|---|
| `shannon/actions/` (entire directory) | Replaced by tool executors |
| `shannon/brain/providers/ollama.py` | No local model support |
| `shannon/brain/providers/memory_base.py` | Replaced by Anthropic memory protocol |
| `shannon/brain/providers/memory_markdown.py` | Replaced by Anthropic memory backend |
| `shannon/brain/providers/base.py` — `LLMProvider` ABC | Single provider, no abstraction needed |
| `shannon/brain/providers/base.py` — `LLMToolDef` | Tools are raw dicts, not dataclasses |
| `shannon/brain/providers/base.py` — `LLMToolDef.server_type` | Dead code from this session |
| All tool constants (`SHELL_TOOL`, `BROWSER_TOOL`, `MOUSE_TOOL`, `KEYBOARD_TOOL`, `WEB_SEARCH_TOOL`, `WEB_FETCH_TOOL`, `CONTINUE_TOOL`, `EXPRESSION_TOOL`) | Replaced by tool registry |
| `TOOL_TO_ACTION` mapping | Deleted with ActionManager |
| `_MEMORY_TOOL_NAMES` set | Deleted with old memory |
| `_build_tools()` conversion in claude.py | Tools arrive as raw dicts |
| `ActionsConfig` + all sub-configs | Replaced by ToolsConfig |
| `apply_dangerously_skip_permissions()` | Replaced by per-tool `require_confirmation` |
| `ActionRequest` / `ActionResult` events | Tools dispatch directly |
| `LLMConfig.type` field | Always "claude" |
| Ollama-related config and CLI args | No local model support |
| `ollama` dependency group in pyproject.toml | Removed |
| `web` dependency group | No local fallbacks needed |
| `aiohttp`, `duckduckgo-search`, `httpx` deps | Server-side web search/fetch, no Ollama |

## New Modules

### `shannon/computer/executor.py`

Self-hosted computer use execution backend. Receives actions from the `computer_20251124` protocol and executes locally via pyautogui and mss.

**All supported actions:**

Basic:
- `screenshot` — capture screen via mss, scale to target resolution, return as base64 PNG
- `left_click` — click at coordinates [x, y]
- `type` — type text string
- `key` — press key or key combination (e.g. "ctrl+s")
- `mouse_move` — move cursor to coordinates

Enhanced:
- `scroll` — scroll in any direction with amount control
- `left_click_drag` — click and drag between coordinates
- `right_click`, `middle_click` — additional mouse buttons
- `double_click`, `triple_click` — multiple clicks
- `left_mouse_down`, `left_mouse_up` — fine-grained click control
- `hold_key` — hold down a key for a specified duration
- `wait` — pause between actions
- `zoom` — view a specific region at full resolution (requires `enable_zoom: true`)

**Screen scaling:** API constrains images to max 1568px longest edge and ~1.15 megapixels. Executor captures at real resolution, scales down for Claude, maps coordinates back for action execution.

### `shannon/computer/screenshot.py`

Screen capture and resolution scaling utilities. Used by both computer use executor (on-demand) and vision system (periodic autonomy captures). Wraps mss.

### `shannon/tools/bash_executor.py`

Persistent bash session backend for `bash_20250124`. Handles:
- `command` — execute shell command, return stdout + stderr
- `restart` — restart the bash session

Wraps asyncio.subprocess with persistent state (env vars, working directory maintained between commands). Safety layer: blocklist validation, timeout enforcement, output truncation.

### `shannon/tools/text_editor_executor.py`

File operation backend for `text_editor_20250728`. Handles:
- `view` — read file contents (with optional line range) or list directory
- `str_replace` — replace exact text match in file (must match exactly once)
- `create` — create new file with content
- `insert` — insert text at specific line number

Path validation (restrict to allowed directories), backup before edit, error messages matching Anthropic's expected format.

### `shannon/tools/memory_backend.py`

Subclass of Anthropic SDK's `BetaAbstractMemoryTool`. File operations against local `memory/` directory:
- `view` — read file or list directory (with size info)
- `create` — create new memory file
- `str_replace` — replace text in memory file
- `insert` — insert text at line
- `delete` — delete memory file/directory
- `rename` — rename/move memory file

Path traversal protection. Response format matches Anthropic's documented format exactly.

## Architecture

### Decompose brain.py

Split the current god object into focused modules:

```
shannon/brain/
├── brain.py            # Event handlers + conversation management only
├── tool_dispatch.py    # ToolDispatcher: name → executor, result formatting
├── tool_registry.py    # ToolRegistry: builds tools list from config
├── claude.py           # Claude API client (was providers/claude.py)
├── prompt.py           # System prompt builder (unchanged)
└── memory.py           # Thin wrapper around memory_backend (may be removed)
```

**brain.py** — subscribes to events, manages conversation history, calls Claude, delegates tool dispatch. ~150 lines.

**tool_dispatch.py** — `ToolDispatcher` class. Takes a tool_use block, routes to the correct executor, returns formatted result. ~100 lines.

**tool_registry.py** — `ToolRegistry` class. Builds the tools list from config (which tools enabled, display dimensions, etc.). Returns `list[dict]` ready for the API. ~60 lines.

**claude.py** — moves up from `providers/claude.py`. No longer behind an ABC. Direct Anthropic SDK client with streaming, adaptive thinking, prompt caching, compaction, beta headers. ~150 lines.

### Remove Provider Abstraction

With only one LLM provider, the `LLMProvider` ABC and `providers/` subdirectory are unnecessary indirection. `claude.py` becomes a direct module in `brain/`. The `LLMMessage`, `LLMToolCall`, `LLMResponse` dataclasses move to a `brain/types.py` or stay in `claude.py`.

### Simplify Config

```python
@dataclass
class LLMConfig:
    model: str = "claude-opus-4-6"
    max_tokens: int = 16000
    api_key: str = ""
    thinking: bool = True       # Adaptive thinking
    compaction: bool = True     # Server-side compaction

@dataclass
class ComputerUseConfig:
    enabled: bool = True
    display_width: int = 1280
    display_height: int = 800
    require_confirmation: bool = True

@dataclass
class BashConfig:
    enabled: bool = True
    require_confirmation: bool = True
    blocklist: list[str] = field(default_factory=lambda: [
        "rm -rf", "sudo", "shutdown", "reboot", "mkfs", "dd if=",
    ])
    timeout_seconds: int = 30

@dataclass
class TextEditorConfig:
    enabled: bool = True
    allowed_dirs: list[str] = field(default_factory=lambda: ["."])

@dataclass
class ToolsConfig:
    computer: ComputerUseConfig = field(default_factory=ComputerUseConfig)
    bash: BashConfig = field(default_factory=BashConfig)
    text_editor: TextEditorConfig = field(default_factory=TextEditorConfig)
```

`--dangerously-skip-permissions` sets `require_confirmation = False` on computer and bash configs.

### Rethink Permissions

Confirmation logic lives in the tool executors, not a central manager. Each executor checks its own `require_confirmation` flag and prompts the user if needed. This is simpler and more local than the old 5-gate ActionManager pipeline.

## Modified Modules

### `shannon/brain/claude.py` (was `providers/claude.py`)

Complete rewrite:
- Uses `client.beta.messages.stream()` with beta headers for all calls
- `generate()` streams internally, returns complete `LLMResponse` via `.get_final_message()`
- Prompt caching: system prompt wrapped with `cache_control`
- Compaction: passes `context_management` parameter, preserves compaction blocks in response
- Adaptive thinking: passes `thinking={"type": "adaptive"}` when enabled
- Beta headers: `["computer-use-2025-11-24", "compact-2026-01-12", "context-1m-2025-08-07"]`
- `_parse_response`: extracts text + tool_use blocks, skips server-side result blocks, captures stop_reason
- No `_build_tools` — tools arrive as raw dicts

### `shannon/brain/memory.py`

Likely deleted entirely. The memory backend (`tools/memory_backend.py`) is dispatched directly by `tool_dispatch.py`. No intermediate wrapper needed unless we want to share the memory directory path.

### `shannon/config.py`

Remove: `LLMConfig.type`, `ActionsConfig` + all sub-configs, `apply_dangerously_skip_permissions()`.
Add: `ToolsConfig`, updated `LLMConfig`.

### `shannon/app.py`

- Remove: ActionManager, all action provider initialization, Ollama provider logic, provider selection logic.
- Initialize: Claude client directly, computer executor, bash executor, text editor executor, memory backend.
- Pass executors to Brain (or to ToolDispatcher).
- Simplified — no conditional provider loading.

### `shannon/events.py`

Remove `ActionRequest` and `ActionResult`.

## Dependencies

### pyproject.toml

```toml
[project]
name = "shannon"
version = "0.2.0"
description = "AI VTuber powered by Claude"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "anthropic>=0.40.0",
]

[project.optional-dependencies]
computer = ["pyautogui>=0.9.54"]
vision = ["mss>=9.0.0", "opencv-python>=4.9.0"]
tts = ["piper-tts>=1.2.0"]
stt = ["faster-whisper>=1.0.0"]
vtuber = ["websockets>=12.0"]
messaging = ["discord.py>=2.3.0"]
all = ["shannon[computer,vision,tts,stt,vtuber,messaging]"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

Key changes:
- `anthropic` moves from optional to **core dependency**
- Remove: `ollama`, `web`, `actions` groups
- Remove: `httpx`, `aiohttp`, `duckduckgo-search`, `playwright`
- `pyautogui` stays in `computer` group (needed for self-hosted computer use)

## Event System

Remove `ActionRequest` and `ActionResult`. Remaining events:

| Event | Purpose |
|---|---|
| `UserInput` | Text/voice input |
| `VisionFrame` | Screen/webcam captures |
| `AutonomousTrigger` | Idle timeout, screen change |
| `LLMResponse` | Structured response (text + expressions + mood) |
| `SpeechStart` / `SpeechEnd` | TTS control |
| `ExpressionChange` | VTuber expression |
| `ConfigChange` | Runtime config updates |
| `ChatMessage` / `ChatResponse` | Discord messages |

## Data Flow

### Computer use + bash + text editor
```
User: "fix the bug in main.py and run the tests"
  → Brain builds tools list from ToolRegistry
  → Claude API call with streaming + adaptive thinking + prompt caching
  → Claude calls str_replace_based_edit_tool(command="view", path="main.py")
  → ToolDispatcher routes to text_editor_executor → reads file → returns contents
  → Claude calls str_replace_based_edit_tool(command="str_replace", ...)
  → ToolDispatcher routes → edits file → returns success
  → Claude calls bash(command="python -m pytest tests/")
  → ToolDispatcher routes to bash_executor → runs in persistent session → returns output
  → Claude returns text: "Fixed the bug and all tests pass."
```

### Computer use for desktop interaction
```
User: "click the login button"
  → Claude calls computer(action="screenshot")
  → ToolDispatcher → computer executor → mss capture → scale → base64 PNG
  → Claude calls computer(action="left_click", coordinate=[540, 320])
  → ToolDispatcher → computer executor → pyautogui.click(scaled_x, scaled_y)
  → Claude returns text: "I clicked the login button."
```

### Web search (fully server-side)
```
User: "what's the latest Python release?"
  → web_search + code_execution run server-side on Anthropic infrastructure
  → Dynamic filtering: code_execution processes results before they reach context
  → Results appear directly in response, no local dispatch needed
  → If stop_reason == "pause_turn", re-send to continue server-side loop
```

### Memory (client-side)
```
  → Claude calls memory(command="view", path="/memories")
  → ToolDispatcher → memory_backend → lists memory/ directory → returns file listing
  → Claude calls memory(command="view", path="/memories/project_context.md")
  → ToolDispatcher → memory_backend → reads file → returns contents with line numbers
  → Claude uses the context, later saves new memories via create/str_replace
```

## Project Layout (After Overhaul)

```
shannon/
├── app.py                  # Entry point, CLI args, module wiring
├── bus.py                  # EventBus (async pub/sub)
├── events.py               # Event dataclasses (10 types, down from 12)
├── config.py               # Config dataclasses + YAML loading
├── brain/
│   ├── brain.py            # Event handlers + conversation management
│   ├── claude.py           # Anthropic API client (streaming, caching, compaction)
│   ├── tool_dispatch.py    # ToolDispatcher: routes tool_use → executors
│   ├── tool_registry.py    # ToolRegistry: builds tools list from config
│   ├── types.py            # LLMMessage, LLMToolCall, LLMResponse
│   └── prompt.py           # System prompt builder
├── computer/
│   ├── executor.py         # Computer use action execution (pyautogui + mss)
│   └── screenshot.py       # Screen capture + resolution scaling
├── tools/
│   ├── bash_executor.py    # Persistent bash session
│   ├── text_editor_executor.py  # File view/edit operations
│   └── memory_backend.py   # BetaAbstractMemoryTool subclass
├── input/                  # InputManager + STTProvider (unchanged)
├── output/                 # OutputManager + TTSProvider + VTuberProvider (unchanged)
├── vision/                 # VisionManager + VisionProvider (unchanged)
├── autonomy/               # AutonomyLoop (unchanged)
└── messaging/              # MessagingManager + DiscordProvider (unchanged)
```

## Testing Strategy

- Unit tests for `computer/executor.py` — mock pyautogui and mss
- Unit tests for `tools/bash_executor.py` — mock subprocess
- Unit tests for `tools/text_editor_executor.py` — test against temp directory
- Unit tests for `tools/memory_backend.py` — test against temp directory
- Unit tests for `brain/tool_dispatch.py` — mock executors, verify routing
- Unit tests for `brain/tool_registry.py` — verify correct tool list from config
- Unit tests for `brain/claude.py` — mock Anthropic SDK, verify streaming/caching/compaction
- Integration tests for brain — FakeLLM returns tool_use blocks, verify full pipeline
- Update config tests for new config shape
- Remove: action manager tests, action provider tests, Ollama provider tests
