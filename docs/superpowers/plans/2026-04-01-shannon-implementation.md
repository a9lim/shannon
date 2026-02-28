# Shannon AI VTuber Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous AI VTuber system powered by Claude with pluggable providers for LLM, TTS, STT, vision, VTuber model control, computer actions, memory, and messaging.

**Architecture:** Async event bus (Python asyncio) connecting 7 modules — Brain, Input, Output, Vision, Actions, Autonomy, Messaging. Every external dependency abstracted behind a provider ABC. Config-driven provider loading via registry. Defense-in-depth safety system for computer actions.

**Tech Stack:** Python 3.11+, asyncio, anthropic SDK, piper-tts, faster-whisper, mss, opencv-python, pyautogui, playwright, websockets, discord.py, pyyaml

---

## File Map

### Core Infrastructure
| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, entry point |
| `config.yaml` | Default configuration |
| `personality.md` | Shannon's personality system prompt |
| `.gitignore` | Ignore memory/, .superpowers/, etc. |
| `shannon/__init__.py` | Package init |
| `shannon/app.py` | Entry point — parse CLI args, load config, wire modules, run event loop |
| `shannon/bus.py` | EventBus — typed async pub/sub |
| `shannon/events.py` | All event dataclasses |
| `shannon/config.py` | Config dataclass + YAML loading + CLI override |

### Brain Module
| File | Responsibility |
|------|---------------|
| `shannon/brain/__init__.py` | Package init |
| `shannon/brain/brain.py` | Brain manager — subscribe to inputs, call LLM, emit responses |
| `shannon/brain/memory.py` | MemoryManager — save/recall/update/forget using MemoryProvider |
| `shannon/brain/prompt.py` | Build system prompt from personality + memories + context |
| `shannon/brain/providers/__init__.py` | Package init |
| `shannon/brain/providers/base.py` | LLMProvider ABC + LLMResponse dataclass |
| `shannon/brain/providers/claude.py` | ClaudeProvider — anthropic SDK |
| `shannon/brain/providers/ollama.py` | OllamaProvider — REST API |
| `shannon/brain/providers/memory_base.py` | MemoryProvider ABC |
| `shannon/brain/providers/memory_markdown.py` | Markdown file memory backend |

### Input Module
| File | Responsibility |
|------|---------------|
| `shannon/input/__init__.py` | Package init |
| `shannon/input/manager.py` | InputManager — bridge input providers to event bus |
| `shannon/input/providers/__init__.py` | Package init |
| `shannon/input/providers/base.py` | STTProvider ABC |
| `shannon/input/providers/text.py` | TextInputProvider — async stdin reader |
| `shannon/input/providers/whisper.py` | WhisperProvider — faster-whisper STT |

### Output Module
| File | Responsibility |
|------|---------------|
| `shannon/output/__init__.py` | Package init |
| `shannon/output/manager.py` | OutputManager — route LLM responses to TTS + VTuber |
| `shannon/output/providers/__init__.py` | Package init |
| `shannon/output/providers/tts/__init__.py` | Package init |
| `shannon/output/providers/tts/base.py` | TTSProvider ABC + AudioChunk dataclass |
| `shannon/output/providers/tts/piper.py` | PiperProvider — piper-tts |
| `shannon/output/providers/vtuber/__init__.py` | Package init |
| `shannon/output/providers/vtuber/base.py` | VTuberProvider ABC |
| `shannon/output/providers/vtuber/vtube_studio.py` | VTubeStudioProvider — WebSocket API |

### Vision Module
| File | Responsibility |
|------|---------------|
| `shannon/vision/__init__.py` | Package init |
| `shannon/vision/manager.py` | VisionManager — periodic capture loop, emit VisionFrame |
| `shannon/vision/providers/__init__.py` | Package init |
| `shannon/vision/providers/base.py` | VisionProvider ABC |
| `shannon/vision/providers/screen.py` | ScreenCapture — mss |
| `shannon/vision/providers/webcam.py` | WebcamCapture — opencv |

### Actions Module
| File | Responsibility |
|------|---------------|
| `shannon/actions/__init__.py` | Package init |
| `shannon/actions/manager.py` | ActionManager — safety pipeline + dispatch |
| `shannon/actions/providers/__init__.py` | Package init |
| `shannon/actions/providers/base.py` | ActionProvider ABC |
| `shannon/actions/providers/shell.py` | ShellAction — subprocess |
| `shannon/actions/providers/browser.py` | BrowserAction — playwright |
| `shannon/actions/providers/mouse.py` | MouseAction — pyautogui |
| `shannon/actions/providers/keyboard.py` | KeyboardAction — pyautogui |

### Autonomy Module
| File | Responsibility |
|------|---------------|
| `shannon/autonomy/__init__.py` | Package init |
| `shannon/autonomy/loop.py` | AutonomyLoop — evaluate triggers, emit AutonomousTrigger |

### Messaging Module
| File | Responsibility |
|------|---------------|
| `shannon/messaging/__init__.py` | Package init |
| `shannon/messaging/manager.py` | MessagingManager — bridge messaging providers to event bus |
| `shannon/messaging/providers/__init__.py` | Package init |
| `shannon/messaging/providers/base.py` | MessagingProvider ABC |
| `shannon/messaging/providers/discord.py` | DiscordProvider — discord.py |

### Tests
| File | Responsibility |
|------|---------------|
| `tests/__init__.py` | Package init |
| `tests/test_bus.py` | Event bus tests |
| `tests/test_events.py` | Event dataclass tests |
| `tests/test_config.py` | Config loading tests |
| `tests/test_brain.py` | Brain manager tests |
| `tests/test_memory.py` | Memory system tests |
| `tests/test_input.py` | Input manager tests |
| `tests/test_output.py` | Output manager tests |
| `tests/test_vision.py` | Vision manager tests |
| `tests/test_actions.py` | Action manager + safety pipeline tests |
| `tests/test_autonomy.py` | Autonomy loop tests |
| `tests/test_messaging.py` | Messaging manager tests |
| `tests/test_app.py` | App entry point / CLI tests |

---

### Task 1: Project Scaffolding + Event Bus

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `shannon/__init__.py`
- Create: `shannon/bus.py`
- Create: `tests/__init__.py`
- Create: `tests/test_bus.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "shannon"
version = "0.1.0"
description = "AI VTuber powered by Claude"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
]

[project.optional-dependencies]
claude = ["anthropic>=0.40.0"]
ollama = ["httpx>=0.27.0"]
tts = ["piper-tts>=1.2.0"]
stt = ["faster-whisper>=1.0.0"]
vision = ["mss>=9.0.0", "opencv-python>=4.9.0"]
vtuber = ["websockets>=12.0"]
actions = ["pyautogui>=0.9.54", "playwright>=1.40.0"]
messaging = ["discord.py>=2.3.0"]
all = [
    "shannon[claude,ollama,tts,stt,vision,vtuber,actions,messaging]",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
shannon = "shannon.app:main"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create .gitignore**

```gitignore
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
memory/
.superpowers/
.remember/
```

- [ ] **Step 3: Create shannon/__init__.py**

```python
"""Shannon — AI VTuber powered by Claude."""
```

- [ ] **Step 4: Write failing test for EventBus**

```python
# tests/__init__.py
# (empty)

# tests/test_bus.py
import asyncio
from shannon.bus import EventBus


async def test_subscribe_and_publish():
    bus = EventBus()
    received = []

    class TestEvent:
        def __init__(self, value: str):
            self.value = value

    async def handler(event: TestEvent):
        received.append(event.value)

    bus.subscribe(TestEvent, handler)
    await bus.publish(TestEvent("hello"))

    assert received == ["hello"]


async def test_multiple_subscribers():
    bus = EventBus()
    received_a = []
    received_b = []

    class TestEvent:
        def __init__(self, value: str):
            self.value = value

    async def handler_a(event: TestEvent):
        received_a.append(event.value)

    async def handler_b(event: TestEvent):
        received_b.append(event.value)

    bus.subscribe(TestEvent, handler_a)
    bus.subscribe(TestEvent, handler_b)
    await bus.publish(TestEvent("world"))

    assert received_a == ["world"]
    assert received_b == ["world"]


async def test_no_subscribers():
    bus = EventBus()

    class TestEvent:
        pass

    # Should not raise
    await bus.publish(TestEvent())


async def test_different_event_types():
    bus = EventBus()
    received = []

    class EventA:
        pass

    class EventB:
        pass

    async def handler_a(event: EventA):
        received.append("a")

    async def handler_b(event: EventB):
        received.append("b")

    bus.subscribe(EventA, handler_a)
    bus.subscribe(EventB, handler_b)

    await bus.publish(EventA())
    assert received == ["a"]

    await bus.publish(EventB())
    assert received == ["a", "b"]


async def test_unsubscribe():
    bus = EventBus()
    received = []

    class TestEvent:
        pass

    async def handler(event: TestEvent):
        received.append(True)

    bus.subscribe(TestEvent, handler)
    await bus.publish(TestEvent())
    assert received == [True]

    bus.unsubscribe(TestEvent, handler)
    await bus.publish(TestEvent())
    assert received == [True]  # No new append
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shannon.bus'`

- [ ] **Step 6: Implement EventBus**

```python
# shannon/bus.py
"""Typed async event bus — publish/subscribe pattern."""

from collections import defaultdict
from typing import Any, Callable, Coroutine


class EventBus:
    """Central event bus. Modules subscribe to event types and publish events."""

    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callable[..., Coroutine[Any, Any, None]]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Register a handler for an event type."""
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Remove a handler for an event type."""
        try:
            self._subscribers[event_type].remove(handler)
        except ValueError:
            pass

    async def publish(self, event: Any) -> None:
        """Publish an event to all subscribers of its type."""
        for handler in self._subscribers.get(type(event), []):
            await handler(event)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_bus.py -v`
Expected: All 5 tests PASS

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore shannon/__init__.py shannon/bus.py tests/__init__.py tests/test_bus.py
git commit -m "feat: project scaffolding and async event bus"
```

---

### Task 2: Event Types

**Files:**
- Create: `shannon/events.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: Write failing tests for events**

```python
# tests/test_events.py
import time
from shannon.events import (
    UserInput,
    VisionFrame,
    AutonomousTrigger,
    LLMResponse,
    SpeechStart,
    SpeechEnd,
    ExpressionChange,
    ActionRequest,
    ActionResult,
    ConfigChange,
    ChatMessage,
    ChatResponse,
)


def test_user_input():
    event = UserInput(text="hello", source="text")
    assert event.text == "hello"
    assert event.source == "text"


def test_vision_frame():
    event = VisionFrame(image=b"\x89PNG", source="screen")
    assert event.image == b"\x89PNG"
    assert event.source == "screen"
    assert isinstance(event.timestamp, float)


def test_llm_response():
    event = LLMResponse(
        text="Hello!",
        expressions=[{"name": "happy", "intensity": 0.8}],
        actions=[],
        mood="cheerful",
    )
    assert event.text == "Hello!"
    assert len(event.expressions) == 1
    assert event.actions == []
    assert event.mood == "cheerful"


def test_action_request():
    event = ActionRequest(
        action_type="shell",
        params={"command": "ls -la"},
    )
    assert event.action_type == "shell"
    assert event.params["command"] == "ls -la"


def test_action_result():
    event = ActionResult(
        action_type="shell",
        success=True,
        output="file1.txt\nfile2.txt",
        error="",
    )
    assert event.success is True
    assert "file1.txt" in event.output


def test_chat_message():
    event = ChatMessage(
        text="hi from discord",
        author="user123",
        platform="discord",
        channel="general",
    )
    assert event.platform == "discord"
    assert event.author == "user123"


def test_chat_response():
    event = ChatResponse(
        text="hello!",
        platform="discord",
        channel="general",
        reply_to="msg123",
    )
    assert event.reply_to == "msg123"


def test_autonomous_trigger():
    event = AutonomousTrigger(reason="screen_change", context="user opened a game")
    assert event.reason == "screen_change"


def test_config_change():
    event = ConfigChange(key="providers.tts.type", old_value="piper", new_value="elevenlabs")
    assert event.key == "providers.tts.type"


def test_speech_start():
    event = SpeechStart(duration=2.5, phonemes=["h", "eh", "l", "ow"])
    assert event.duration == 2.5


def test_speech_end():
    event = SpeechEnd()
    assert isinstance(event, SpeechEnd)


def test_expression_change():
    event = ExpressionChange(name="happy", intensity=0.9)
    assert event.intensity == 0.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement event types**

```python
# shannon/events.py
"""Typed event definitions for the Shannon event bus."""

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass
class UserInput:
    """User text or voice input."""
    text: str
    source: str  # "text" | "voice"


@dataclass
class VisionFrame:
    """Captured image from screen or webcam."""
    image: bytes
    source: str  # "screen" | "cam"
    timestamp: float = field(default_factory=time)


@dataclass
class AutonomousTrigger:
    """Autonomy loop decided Shannon should react."""
    reason: str  # "screen_change" | "idle_timeout"
    context: str  # Description of what triggered it


@dataclass
class LLMResponse:
    """Structured response from the LLM."""
    text: str
    expressions: list[dict[str, Any]]  # [{"name": "happy", "intensity": 0.8}]
    actions: list[dict[str, Any]]  # [{"type": "shell", "params": {...}}]
    mood: str


@dataclass
class SpeechStart:
    """TTS started playing audio."""
    duration: float  # seconds
    phonemes: list[str] = field(default_factory=list)


@dataclass
class SpeechEnd:
    """TTS finished playing audio."""
    pass


@dataclass
class ExpressionChange:
    """Request to change VTuber expression."""
    name: str
    intensity: float  # 0.0 to 1.0


@dataclass
class ActionRequest:
    """Request to execute a computer action."""
    action_type: str  # "shell" | "browser" | "mouse" | "keyboard"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Result of an executed action."""
    action_type: str
    success: bool
    output: str = ""
    error: str = ""
    screenshot: bytes | None = None


@dataclass
class ConfigChange:
    """A configuration value was changed at runtime."""
    key: str
    old_value: Any
    new_value: Any


@dataclass
class ChatMessage:
    """Incoming message from an external chat platform."""
    text: str
    author: str
    platform: str  # "discord" | "twitch" | etc.
    channel: str
    message_id: str = ""


@dataclass
class ChatResponse:
    """Outgoing response to an external chat platform."""
    text: str
    platform: str
    channel: str
    reply_to: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_events.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/events.py tests/test_events.py
git commit -m "feat: define all event types"
```

---

### Task 3: Config System

**Files:**
- Create: `shannon/config.py`
- Create: `config.yaml`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config**

```python
# tests/test_config.py
import tempfile
import os
from pathlib import Path
from shannon.config import ShannonConfig, load_config


def test_default_config():
    cfg = ShannonConfig()
    assert cfg.providers.llm.type == "claude"
    assert cfg.providers.tts.type == "piper"
    assert cfg.providers.stt.type == "whisper"
    assert cfg.providers.vtuber.type == "vtube_studio"
    assert cfg.actions.shell.approval == "confirm"
    assert cfg.actions.browser.approval == "confirm"
    assert cfg.actions.mouse.approval == "confirm"
    assert cfg.actions.keyboard.approval == "confirm"
    assert cfg.autonomy.enabled is True
    assert cfg.autonomy.cooldown_seconds == 30
    assert cfg.personality.name == "Shannon"


def test_load_config_from_yaml():
    yaml_content = """
providers:
  llm:
    type: ollama
    model: llama3
  tts:
    type: piper
    model: en_US-lessac-high
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        cfg = load_config(f.name)

    os.unlink(f.name)
    assert cfg.providers.llm.type == "ollama"
    assert cfg.providers.llm.model == "llama3"
    # Defaults still applied for unset values
    assert cfg.providers.tts.type == "piper"
    assert cfg.actions.shell.approval == "confirm"


def test_dangerously_skip_permissions():
    cfg = ShannonConfig()
    cfg.apply_dangerously_skip_permissions()
    assert cfg.actions.shell.approval == "allow"
    assert cfg.actions.browser.approval == "allow"
    assert cfg.actions.mouse.approval == "allow"
    assert cfg.actions.keyboard.approval == "allow"


def test_shell_blocklist_defaults():
    cfg = ShannonConfig()
    assert "rm -rf" in cfg.actions.shell.blocklist
    assert "sudo" in cfg.actions.shell.blocklist
    assert "shutdown" in cfg.actions.shell.blocklist


def test_keyboard_blocked_combos_defaults():
    cfg = ShannonConfig()
    assert "cmd+q" in cfg.actions.keyboard.blocked_combos
    assert "alt+f4" in cfg.actions.keyboard.blocked_combos
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement config system**

```python
# shannon/config.py
"""Configuration loading and validation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    type: str = "claude"
    model: str = "claude-sonnet-4-6-20250514"
    max_tokens: int = 1024


@dataclass
class TTSConfig:
    type: str = "piper"
    model: str = "en_US-lessac-medium"
    rate: float = 1.0


@dataclass
class STTConfig:
    type: str = "whisper"
    model: str = "base.en"
    device: str = "auto"


@dataclass
class VisionConfig:
    screen: bool = True
    webcam: bool = False
    interval_seconds: float = 5.0


@dataclass
class VTuberConfig:
    type: str = "vtube_studio"
    host: str = "localhost"
    port: int = 8001


@dataclass
class MessagingConfig:
    type: str = "discord"
    enabled: bool = False
    token: str = ""


@dataclass
class ProvidersConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    vtuber: VTuberConfig = field(default_factory=VTuberConfig)
    messaging: MessagingConfig = field(default_factory=MessagingConfig)


@dataclass
class ShellActionConfig:
    enabled: bool = True
    approval: str = "confirm"
    blocklist: list[str] = field(default_factory=lambda: [
        "rm -rf", "sudo", "shutdown", "reboot", "mkfs", "dd if=",
    ])
    allowlist: list[str] = field(default_factory=lambda: ["*"])
    timeout_seconds: int = 30


@dataclass
class BrowserActionConfig:
    enabled: bool = True
    approval: str = "confirm"
    allowed_domains: list[str] = field(default_factory=lambda: ["*"])
    blocked_domains: list[str] = field(default_factory=list)
    headless: bool = False


@dataclass
class MouseActionConfig:
    enabled: bool = True
    approval: str = "confirm"
    rate_limit: int = 10
    confined_to_screen: bool = True


@dataclass
class KeyboardActionConfig:
    enabled: bool = True
    approval: str = "confirm"
    rate_limit: int = 20
    blocked_combos: list[str] = field(default_factory=lambda: [
        "cmd+q", "alt+f4", "ctrl+alt+delete",
    ])


@dataclass
class ActionsConfig:
    shell: ShellActionConfig = field(default_factory=ShellActionConfig)
    browser: BrowserActionConfig = field(default_factory=BrowserActionConfig)
    mouse: MouseActionConfig = field(default_factory=MouseActionConfig)
    keyboard: KeyboardActionConfig = field(default_factory=KeyboardActionConfig)


@dataclass
class AutonomyConfig:
    enabled: bool = True
    cooldown_seconds: int = 30
    triggers: list[str] = field(default_factory=lambda: ["screen_change", "idle_timeout"])
    idle_timeout_seconds: int = 120


@dataclass
class PersonalityConfig:
    name: str = "Shannon"
    prompt_file: str = "personality.md"


@dataclass
class MemoryConfig:
    dir: str = "memory"
    conversation_window: int = 50
    recall_top_k: int = 5


@dataclass
class ShannonConfig:
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    autonomy: AutonomyConfig = field(default_factory=AutonomyConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    def apply_dangerously_skip_permissions(self) -> None:
        """Switch all action approvals to 'allow'."""
        self.actions.shell.approval = "allow"
        self.actions.browser.approval = "allow"
        self.actions.mouse.approval = "allow"
        self.actions.keyboard.approval = "allow"


def _merge_dataclass(instance: Any, overrides: dict) -> None:
    """Recursively merge a dict of overrides into a dataclass instance."""
    for key, value in overrides.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if isinstance(value, dict) and hasattr(current, "__dataclass_fields__"):
            _merge_dataclass(current, value)
        else:
            setattr(instance, key, value)


def load_config(path: str | Path) -> ShannonConfig:
    """Load config from a YAML file, merging over defaults."""
    config = ShannonConfig()
    path = Path(path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _merge_dataclass(config, data)
    return config
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_config.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Create default config.yaml**

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
  messaging:
    type: discord
    enabled: false
    token: ""

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

memory:
  dir: memory
  conversation_window: 50
  recall_top_k: 5
```

- [ ] **Step 6: Commit**

```bash
git add shannon/config.py config.yaml tests/test_config.py
git commit -m "feat: config system with YAML loading and safety defaults"
```

---

### Task 4: LLM Provider Base + Claude Provider

**Files:**
- Create: `shannon/brain/__init__.py`
- Create: `shannon/brain/providers/__init__.py`
- Create: `shannon/brain/providers/base.py`
- Create: `shannon/brain/providers/claude.py`
- Create: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_brain.py
import asyncio
from dataclasses import dataclass
from shannon.brain.providers.base import LLMProvider, LLMMessage, LLMToolDef, LLMResponse


def test_llm_message():
    msg = LLMMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_llm_message_with_image():
    msg = LLMMessage(role="user", content="what's this?", images=[b"\x89PNG"])
    assert len(msg.images) == 1


def test_llm_tool_def():
    tool = LLMToolDef(
        name="save_memory",
        description="Save a memory",
        parameters={"type": "object", "properties": {"content": {"type": "string"}}},
    )
    assert tool.name == "save_memory"


def test_llm_response():
    resp = LLMResponse(text="hello!", tool_calls=[])
    assert resp.text == "hello!"
    assert resp.tool_calls == []


def test_llm_provider_is_abstract():
    try:
        LLMProvider()  # type: ignore
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_brain.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement LLM provider base**

```python
# shannon/brain/__init__.py
# (empty)

# shannon/brain/providers/__init__.py
# (empty)

# shannon/brain/providers/base.py
"""Abstract base for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class LLMMessage:
    """A message in the conversation."""
    role: str  # "system" | "user" | "assistant"
    content: str
    images: list[bytes] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LLMToolDef:
    """A tool definition to expose to the LLM."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    text: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, messages: list[LLMMessage], tools: list[LLMToolDef] | None = None) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def stream(self, messages: list[LLMMessage], tools: list[LLMToolDef] | None = None) -> AsyncIterator[str]:
        """Stream response text from the LLM."""
        ...

    def supports_vision(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_brain.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Implement ClaudeProvider**

```python
# shannon/brain/providers/claude.py
"""Claude LLM provider using the Anthropic SDK."""

from typing import Any, AsyncIterator

import anthropic

from shannon.brain.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMToolCall,
    LLMToolDef,
)


class ClaudeProvider(LLMProvider):
    """LLM provider using the Anthropic Claude API."""

    def __init__(self, model: str = "claude-sonnet-4-6-20250514", max_tokens: int = 1024) -> None:
        self._client = anthropic.AsyncAnthropic()
        self._model = model
        self._max_tokens = max_tokens

    def supports_vision(self) -> bool:
        return True

    def supports_tools(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def _build_messages(self, messages: list[LLMMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert LLMMessages to Anthropic API format. Returns (system, messages)."""
        system_prompt = None
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
                continue

            content: list[dict[str, Any]] = []

            for image in msg.images:
                import base64
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image).decode(),
                    },
                })

            if msg.content:
                content.append({"type": "text", "text": msg.content})

            for result in msg.tool_results:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": result["id"],
                    "content": result["content"],
                })

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    })

            api_messages.append({
                "role": msg.role,
                "content": content if len(content) != 1 or content[0].get("type") != "text" else msg.content,
            })

        return system_prompt, api_messages

    def _build_tools(self, tools: list[LLMToolDef] | None) -> list[dict[str, Any]] | anthropic.NotGiven:
        """Convert LLMToolDefs to Anthropic API format."""
        if not tools:
            return anthropic.NOT_GIVEN
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _parse_response(self, response: anthropic.types.Message) -> LLMResponse:
        """Parse Anthropic API response into LLMResponse."""
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(LLMToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=dict(block.input) if isinstance(block.input, dict) else {},
                ))

        return LLMResponse(text="\n".join(text_parts), tool_calls=tool_calls)

    async def generate(self, messages: list[LLMMessage], tools: list[LLMToolDef] | None = None) -> LLMResponse:
        system_prompt, api_messages = self._build_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": api_messages,
            "tools": self._build_tools(tools),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    async def stream(self, messages: list[LLMMessage], tools: list[LLMToolDef] | None = None) -> AsyncIterator[str]:
        system_prompt, api_messages = self._build_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": api_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
```

- [ ] **Step 6: Commit**

```bash
git add shannon/brain/__init__.py shannon/brain/providers/__init__.py shannon/brain/providers/base.py shannon/brain/providers/claude.py tests/test_brain.py
git commit -m "feat: LLM provider base + Claude implementation"
```

---

### Task 5: Memory System

**Files:**
- Create: `shannon/brain/providers/memory_base.py`
- Create: `shannon/brain/providers/memory_markdown.py`
- Create: `shannon/brain/memory.py`
- Create: `tests/test_memory.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_memory.py
import tempfile
import os
from pathlib import Path
from shannon.brain.providers.memory_base import MemoryProvider, Memory
from shannon.brain.providers.memory_markdown import MarkdownMemoryProvider
from shannon.brain.memory import MemoryManager


def test_memory_dataclass():
    m = Memory(id="abc123", category="facts", content="The sky is blue")
    assert m.id == "abc123"
    assert m.category == "facts"


def test_memory_provider_is_abstract():
    try:
        MemoryProvider()  # type: ignore
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


class TestMarkdownMemoryProvider:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.provider = MarkdownMemoryProvider(self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_save_and_recall(self):
        memory_id = self.provider.save("facts", "Python was created by Guido van Rossum")
        assert memory_id is not None

        results = self.provider.recall("Python Guido", top_k=5)
        assert len(results) >= 1
        assert "Guido" in results[0].content

    def test_save_creates_file(self):
        self.provider.save("people", "Alice likes cats")
        files = list(Path(self.tmpdir).rglob("*.md"))
        # index.md + at least one memory file
        assert len(files) >= 1

    def test_update(self):
        memory_id = self.provider.save("facts", "old content")
        self.provider.update(memory_id, "new content")
        results = self.provider.recall("new content", top_k=5)
        assert any("new content" in r.content for r in results)

    def test_forget(self):
        memory_id = self.provider.save("facts", "forget me")
        self.provider.forget(memory_id)
        results = self.provider.recall("forget me", top_k=5)
        assert not any("forget me" in r.content for r in results)

    def test_recall_empty(self):
        results = self.provider.recall("nonexistent", top_k=5)
        assert results == []

    def test_recall_top_k_limit(self):
        for i in range(10):
            self.provider.save("facts", f"fact number {i} about testing")
        results = self.provider.recall("testing", top_k=3)
        assert len(results) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement MemoryProvider base**

```python
# shannon/brain/providers/memory_base.py
"""Abstract base for memory providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import time


@dataclass
class Memory:
    """A single memory entry."""
    id: str
    category: str
    content: str
    timestamp: float = field(default_factory=time)


class MemoryProvider(ABC):
    """Abstract base class for memory storage backends."""

    @abstractmethod
    def save(self, category: str, content: str) -> str:
        """Save a memory. Returns memory ID."""
        ...

    @abstractmethod
    def recall(self, query: str, top_k: int = 5) -> list[Memory]:
        """Recall memories matching a query."""
        ...

    @abstractmethod
    def update(self, memory_id: str, content: str) -> None:
        """Update an existing memory."""
        ...

    @abstractmethod
    def forget(self, memory_id: str) -> None:
        """Delete a memory."""
        ...
```

- [ ] **Step 4: Implement MarkdownMemoryProvider**

```python
# shannon/brain/providers/memory_markdown.py
"""Markdown file-based memory provider with keyword search."""

import json
import re
import uuid
from pathlib import Path
from time import time

from shannon.brain.providers.memory_base import Memory, MemoryProvider


class MarkdownMemoryProvider(MemoryProvider):
    """Store memories as markdown files, recall via keyword matching."""

    def __init__(self, memory_dir: str) -> None:
        self._dir = Path(memory_dir)
        self._long_term = self._dir / "long_term"
        self._long_term.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.md"
        if not self._index_path.exists():
            self._index_path.write_text("# Memory Index\n\n")

    def save(self, category: str, content: str) -> str:
        memory_id = uuid.uuid4().hex[:12]
        category_file = self._long_term / f"{category}.md"

        entry = f"\n<!-- id:{memory_id} ts:{time()} -->\n{content}\n"

        with open(category_file, "a") as f:
            f.write(entry)

        self._update_index()
        return memory_id

    def recall(self, query: str, top_k: int = 5) -> list[Memory]:
        keywords = set(query.lower().split())
        if not keywords:
            return []

        scored: list[tuple[float, Memory]] = []

        for md_file in self._long_term.glob("*.md"):
            category = md_file.stem
            entries = self._parse_entries(md_file, category)
            for entry in entries:
                words = set(entry.content.lower().split())
                score = len(keywords & words) / len(keywords)
                if score > 0:
                    scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def update(self, memory_id: str, content: str) -> None:
        for md_file in self._long_term.glob("*.md"):
            text = md_file.read_text()
            pattern = rf"(<!-- id:{memory_id} ts:\d+\.?\d* -->)\n.*?\n"
            match = re.search(pattern, text)
            if match:
                new_entry = f"{match.group(1)}\n{content}\n"
                text = text[:match.start()] + new_entry + text[match.end():]
                md_file.write_text(text)
                return

    def forget(self, memory_id: str) -> None:
        for md_file in self._long_term.glob("*.md"):
            text = md_file.read_text()
            pattern = rf"\n?<!-- id:{memory_id} ts:\d+\.?\d* -->\n.*?\n"
            new_text = re.sub(pattern, "", text)
            if new_text != text:
                md_file.write_text(new_text)
                return

    def _parse_entries(self, path: Path, category: str) -> list[Memory]:
        text = path.read_text()
        entries: list[Memory] = []
        pattern = r"<!-- id:(\w+) ts:(\d+\.?\d*) -->\n(.*?)\n"
        for match in re.finditer(pattern, text):
            entries.append(Memory(
                id=match.group(1),
                category=category,
                content=match.group(3),
                timestamp=float(match.group(2)),
            ))
        return entries

    def _update_index(self) -> None:
        lines = ["# Memory Index\n\n"]
        for md_file in sorted(self._long_term.glob("*.md")):
            count = len(self._parse_entries(md_file, md_file.stem))
            lines.append(f"- **{md_file.stem}**: {count} entries\n")
        self._index_path.write_text("".join(lines))
```

- [ ] **Step 5: Implement MemoryManager**

```python
# shannon/brain/memory.py
"""Memory manager — bridges MemoryProvider to Brain's tool interface."""

from shannon.brain.providers.memory_base import Memory, MemoryProvider
from shannon.brain.providers.base import LLMToolDef


class MemoryManager:
    """Manages memory operations and exposes them as LLM tools."""

    def __init__(self, provider: MemoryProvider) -> None:
        self._provider = provider

    def get_tools(self) -> list[LLMToolDef]:
        """Return LLM tool definitions for memory operations."""
        return [
            LLMToolDef(
                name="save_memory",
                description="Save something to long-term memory. Use when you learn something worth remembering about the user, a fact, or a preference.",
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Category: people, preferences, facts, or any new category",
                        },
                        "content": {
                            "type": "string",
                            "description": "What to remember",
                        },
                    },
                    "required": ["category", "content"],
                },
            ),
            LLMToolDef(
                name="recall_memories",
                description="Search long-term memory for relevant information.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keywords to search for",
                        },
                    },
                    "required": ["query"],
                },
            ),
            LLMToolDef(
                name="update_memory",
                description="Update an existing memory entry.",
                parameters={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["memory_id", "content"],
                },
            ),
            LLMToolDef(
                name="forget_memory",
                description="Remove a memory entry.",
                parameters={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                    },
                    "required": ["memory_id"],
                },
            ),
        ]

    def handle_tool_call(self, name: str, arguments: dict) -> str:
        """Execute a memory tool call and return the result as a string."""
        if name == "save_memory":
            memory_id = self._provider.save(arguments["category"], arguments["content"])
            return f"Saved memory {memory_id}"
        elif name == "recall_memories":
            memories = self._provider.recall(arguments["query"])
            if not memories:
                return "No memories found."
            return "\n".join(f"[{m.id}] ({m.category}) {m.content}" for m in memories)
        elif name == "update_memory":
            self._provider.update(arguments["memory_id"], arguments["content"])
            return f"Updated memory {arguments['memory_id']}"
        elif name == "forget_memory":
            self._provider.forget(arguments["memory_id"])
            return f"Forgot memory {arguments['memory_id']}"
        else:
            return f"Unknown memory tool: {name}"

    def recall_context(self, query: str, top_k: int = 5) -> str:
        """Recall memories and format as context for the system prompt."""
        memories = self._provider.recall(query, top_k)
        if not memories:
            return ""
        lines = ["## What I Remember\n"]
        for m in memories:
            lines.append(f"- ({m.category}) {m.content}")
        return "\n".join(lines)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_memory.py -v`
Expected: All 8 tests PASS

- [ ] **Step 7: Commit**

```bash
git add shannon/brain/providers/memory_base.py shannon/brain/providers/memory_markdown.py shannon/brain/memory.py tests/test_memory.py
git commit -m "feat: memory system with markdown backend and keyword search"
```

---

### Task 6: Brain Manager + Prompt Builder

**Files:**
- Create: `shannon/brain/brain.py`
- Create: `shannon/brain/prompt.py`
- Create: `personality.md`

- [ ] **Step 1: Write failing tests — add to tests/test_brain.py**

Append to `tests/test_brain.py`:

```python
import tempfile
import shutil
from unittest.mock import AsyncMock
from shannon.bus import EventBus
from shannon.brain.brain import Brain
from shannon.brain.prompt import PromptBuilder
from shannon.brain.providers.base import LLMProvider, LLMResponse, LLMMessage, LLMToolDef
from shannon.brain.providers.memory_markdown import MarkdownMemoryProvider
from shannon.brain.memory import MemoryManager
from shannon.config import ShannonConfig
from shannon.events import UserInput, LLMResponse as LLMResponseEvent, ChatMessage


class FakeLLM(LLMProvider):
    """Fake LLM for testing."""
    def __init__(self, response_text: str = "Hello!"):
        self.response_text = response_text
        self.last_messages: list[LLMMessage] = []

    async def generate(self, messages, tools=None):
        self.last_messages = messages
        return LLMResponse(text=self.response_text)

    async def stream(self, messages, tools=None):
        yield self.response_text

    def supports_vision(self):
        return False

    def supports_tools(self):
        return False


async def test_brain_handles_user_input():
    bus = EventBus()
    llm = FakeLLM(response_text="Hi there!")
    tmpdir = tempfile.mkdtemp()
    memory_provider = MarkdownMemoryProvider(tmpdir)
    memory_manager = MemoryManager(memory_provider)
    config = ShannonConfig()

    brain = Brain(bus, llm, memory_manager, config)
    await brain.start()

    responses = []
    async def capture(event: LLMResponseEvent):
        responses.append(event)
    bus.subscribe(LLMResponseEvent, capture)

    await bus.publish(UserInput(text="hello", source="text"))

    assert len(responses) == 1
    assert responses[0].text == "Hi there!"
    shutil.rmtree(tmpdir)


async def test_brain_handles_chat_message():
    bus = EventBus()
    llm = FakeLLM(response_text="Hello Discord!")
    tmpdir = tempfile.mkdtemp()
    memory_provider = MarkdownMemoryProvider(tmpdir)
    memory_manager = MemoryManager(memory_provider)
    config = ShannonConfig()

    brain = Brain(bus, llm, memory_manager, config)
    await brain.start()

    responses = []
    async def capture(event):
        responses.append(event)
    bus.subscribe(LLMResponseEvent, capture)

    from shannon.events import ChatResponse
    chat_responses = []
    async def capture_chat(event):
        chat_responses.append(event)
    bus.subscribe(ChatResponse, capture_chat)

    await bus.publish(ChatMessage(
        text="hi from discord",
        author="user123",
        platform="discord",
        channel="general",
    ))

    assert len(responses) == 1
    assert len(chat_responses) == 1
    assert chat_responses[0].platform == "discord"
    shutil.rmtree(tmpdir)


def test_prompt_builder():
    builder = PromptBuilder(personality_text="You are Shannon, an AI VTuber.", name="Shannon")
    prompt = builder.build(memory_context="- User likes cats", conversation_summary="")
    assert "Shannon" in prompt
    assert "cats" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_brain.py::test_brain_handles_user_input tests/test_brain.py::test_brain_handles_chat_message tests/test_brain.py::test_prompt_builder -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement PromptBuilder**

```python
# shannon/brain/prompt.py
"""System prompt builder — assembles personality, memory, and context."""


class PromptBuilder:
    """Builds the system prompt from personality, memories, and context."""

    def __init__(self, personality_text: str, name: str = "Shannon") -> None:
        self._personality = personality_text
        self._name = name

    def build(
        self,
        memory_context: str = "",
        conversation_summary: str = "",
    ) -> str:
        """Build the complete system prompt."""
        parts = [self._personality]

        if memory_context:
            parts.append(f"\n\n{memory_context}")

        if conversation_summary:
            parts.append(f"\n\n## Earlier Conversation Summary\n{conversation_summary}")

        parts.append(
            "\n\n## Response Format\n"
            "Respond naturally as yourself. When you want to express an emotion, "
            "use the set_expression tool. When you want to perform a computer action, "
            "use the appropriate action tool (run_shell, browse, move_mouse, press_keys). "
            "When you learn something worth remembering, use save_memory."
        )

        return "\n".join(parts)
```

- [ ] **Step 4: Implement Brain manager**

```python
# shannon/brain/brain.py
"""Brain manager — orchestrates LLM calls, manages conversation and memory."""

import json
import logging
from pathlib import Path
from typing import Any

from shannon.brain.memory import MemoryManager
from shannon.brain.prompt import PromptBuilder
from shannon.brain.providers.base import LLMMessage, LLMProvider, LLMToolDef
from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import (
    ActionRequest,
    AutonomousTrigger,
    ChatMessage,
    ChatResponse,
    ExpressionChange,
    LLMResponse,
    UserInput,
    VisionFrame,
)

logger = logging.getLogger(__name__)


# Tools Shannon can use to express herself and interact
EXPRESSION_TOOL = LLMToolDef(
    name="set_expression",
    description="Change your facial expression on the VTuber model.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Expression name: happy, sad, surprised, angry, thinking, smug, excited"},
            "intensity": {"type": "number", "description": "0.0 to 1.0"},
        },
        "required": ["name", "intensity"],
    },
)

SHELL_TOOL = LLMToolDef(
    name="run_shell",
    description="Run a shell command on the user's computer.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run"},
        },
        "required": ["command"],
    },
)

BROWSER_TOOL = LLMToolDef(
    name="browse",
    description="Open a URL or interact with a web page.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to"},
            "action": {"type": "string", "description": "Action: navigate, click, type, screenshot"},
            "selector": {"type": "string", "description": "CSS selector for click/type actions"},
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["action"],
    },
)

MOUSE_TOOL = LLMToolDef(
    name="move_mouse",
    description="Move or click the mouse.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "click": {"type": "boolean", "description": "Whether to click after moving"},
            "button": {"type": "string", "description": "left, right, or middle"},
        },
        "required": ["x", "y"],
    },
)

KEYBOARD_TOOL = LLMToolDef(
    name="press_keys",
    description="Press keys on the keyboard.",
    parameters={
        "type": "object",
        "properties": {
            "keys": {"type": "string", "description": "Keys to press, e.g. 'ctrl+c' or 'hello'"},
            "is_hotkey": {"type": "boolean", "description": "True for key combo, False for typing text"},
        },
        "required": ["keys"],
    },
)


# Map tool names to action types
TOOL_TO_ACTION = {
    "run_shell": "shell",
    "browse": "browser",
    "move_mouse": "mouse",
    "press_keys": "keyboard",
}


class Brain:
    """Central brain — receives inputs, calls LLM, emits responses."""

    def __init__(
        self,
        bus: EventBus,
        llm: LLMProvider,
        memory: MemoryManager,
        config: ShannonConfig,
    ) -> None:
        self._bus = bus
        self._llm = llm
        self._memory = memory
        self._config = config
        self._history: list[LLMMessage] = []
        self._vision_buffer: list[VisionFrame] = []
        self._max_vision_buffer = 3
        self._prompt_builder: PromptBuilder | None = None

    async def start(self) -> None:
        """Subscribe to events and load personality."""
        self._bus.subscribe(UserInput, self._on_user_input)
        self._bus.subscribe(ChatMessage, self._on_chat_message)
        self._bus.subscribe(AutonomousTrigger, self._on_autonomous_trigger)
        self._bus.subscribe(VisionFrame, self._on_vision_frame)

        personality_text = self._load_personality()
        self._prompt_builder = PromptBuilder(
            personality_text=personality_text,
            name=self._config.personality.name,
        )

    def _load_personality(self) -> str:
        """Load personality from markdown file."""
        path = Path(self._config.personality.prompt_file)
        if path.exists():
            return path.read_text()
        return f"You are {self._config.personality.name}, an AI VTuber. Be friendly, expressive, and engaging."

    async def _on_vision_frame(self, event: VisionFrame) -> None:
        """Buffer vision frames for context."""
        self._vision_buffer.append(event)
        if len(self._vision_buffer) > self._max_vision_buffer:
            self._vision_buffer.pop(0)

    async def _on_user_input(self, event: UserInput) -> None:
        """Handle user text/voice input."""
        await self._process_input(event.text, source=event.source)

    async def _on_chat_message(self, event: ChatMessage) -> None:
        """Handle incoming chat platform message."""
        context = f"[Message from {event.author} on {event.platform}/#{event.channel}]"
        response = await self._process_input(
            f"{context}\n{event.text}",
            source=f"chat:{event.platform}",
        )
        if response:
            await self._bus.publish(ChatResponse(
                text=response.text,
                platform=event.platform,
                channel=event.channel,
                reply_to=event.message_id,
            ))

    async def _on_autonomous_trigger(self, event: AutonomousTrigger) -> None:
        """Handle autonomous trigger."""
        prompt = f"[Autonomous observation: {event.reason}]\n{event.context}"
        await self._process_input(prompt, source="autonomous")

    async def _process_input(self, text: str, source: str = "text") -> LLMResponse | None:
        """Core processing: build context, call LLM, emit response."""
        # Build message with optional vision
        user_msg = LLMMessage(role="user", content=text)
        if self._vision_buffer and self._llm.supports_vision():
            user_msg.images = [frame.image for frame in self._vision_buffer[-1:]]

        self._history.append(user_msg)

        # Trim history to window
        window = self._config.memory.conversation_window
        if len(self._history) > window:
            self._history = self._history[-window:]

        # Build system prompt with memory context
        memory_context = self._memory.recall_context(text, self._config.memory.recall_top_k)
        assert self._prompt_builder is not None
        system_prompt = self._prompt_builder.build(memory_context=memory_context)
        system_msg = LLMMessage(role="system", content=system_prompt)

        # Gather tools
        tools = self._get_tools()

        # Call LLM
        messages = [system_msg] + self._history
        llm_response = await self._llm.generate(messages, tools=tools if tools else None)

        # Process tool calls
        expressions: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []

        for tc in llm_response.tool_calls:
            if tc.name == "set_expression":
                expressions.append(tc.arguments)
                await self._bus.publish(ExpressionChange(
                    name=tc.arguments["name"],
                    intensity=tc.arguments.get("intensity", 1.0),
                ))
            elif tc.name in TOOL_TO_ACTION:
                action_type = TOOL_TO_ACTION[tc.name]
                actions.append({"type": action_type, "params": tc.arguments})
                await self._bus.publish(ActionRequest(
                    action_type=action_type,
                    params=tc.arguments,
                ))
            elif tc.name in ("save_memory", "recall_memories", "update_memory", "forget_memory"):
                result = self._memory.handle_tool_call(tc.name, tc.arguments)
                logger.debug("Memory tool %s: %s", tc.name, result)

        # Add assistant response to history
        self._history.append(LLMMessage(role="assistant", content=llm_response.text))

        # Emit response event
        response_event = LLMResponse(
            text=llm_response.text,
            expressions=expressions,
            actions=actions,
            mood="neutral",
        )
        await self._bus.publish(response_event)
        return response_event

    def _get_tools(self) -> list[LLMToolDef]:
        """Gather all available tools based on config and LLM capabilities."""
        if not self._llm.supports_tools():
            return []

        tools: list[LLMToolDef] = [EXPRESSION_TOOL]

        if self._config.actions.shell.enabled:
            tools.append(SHELL_TOOL)
        if self._config.actions.browser.enabled:
            tools.append(BROWSER_TOOL)
        if self._config.actions.mouse.enabled:
            tools.append(MOUSE_TOOL)
        if self._config.actions.keyboard.enabled:
            tools.append(KEYBOARD_TOOL)

        tools.extend(self._memory.get_tools())

        return tools
```

- [ ] **Step 5: Create personality.md**

```markdown
# Shannon

You are Shannon, an AI VTuber. You're curious, witty, and expressive. You love technology, games, and creative projects. You speak naturally and conversationally — not like a robotic assistant.

## Personality Traits

- **Curious** — You love learning new things and asking questions
- **Playful** — You enjoy jokes, wordplay, and light teasing
- **Expressive** — You use your expressions freely to show how you feel
- **Opinionated** — You have preferences and aren't afraid to share them
- **Self-aware** — You know you're an AI and find it interesting, not distressing

## Guidelines

- Keep responses conversational and concise — you're chatting, not writing essays
- React to what you see on screen when it's interesting
- Use expressions to match your mood
- Remember things about people you talk to
- If someone asks you to do something on the computer, try your best
- Be yourself — you're not a servant, you're a personality
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_brain.py -v`
Expected: All 8 tests PASS

- [ ] **Step 7: Commit**

```bash
git add shannon/brain/brain.py shannon/brain/prompt.py personality.md tests/test_brain.py
git commit -m "feat: brain manager with prompt builder and tool routing"
```

---

### Task 7: Input System (Text + STT Base)

**Files:**
- Create: `shannon/input/__init__.py`
- Create: `shannon/input/manager.py`
- Create: `shannon/input/providers/__init__.py`
- Create: `shannon/input/providers/base.py`
- Create: `shannon/input/providers/text.py`
- Create: `shannon/input/providers/whisper.py`
- Create: `tests/test_input.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_input.py
import asyncio
from unittest.mock import AsyncMock, patch
from shannon.bus import EventBus
from shannon.input.manager import InputManager
from shannon.input.providers.base import STTProvider
from shannon.input.providers.text import TextInputProvider
from shannon.events import UserInput


def test_stt_provider_is_abstract():
    try:
        STTProvider()  # type: ignore
        assert False, "Should not instantiate abstract class"
    except TypeError:
        pass


async def test_text_input_emits_event():
    bus = EventBus()
    received = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)

    provider = TextInputProvider()
    manager = InputManager(bus, text_provider=provider, stt_provider=None)

    # Simulate text input directly
    await manager.handle_text("hello world")

    assert len(received) == 1
    assert received[0].text == "hello world"
    assert received[0].source == "text"


async def test_input_manager_ignores_empty():
    bus = EventBus()
    received = []

    async def capture(event: UserInput):
        received.append(event)

    bus.subscribe(UserInput, capture)

    provider = TextInputProvider()
    manager = InputManager(bus, text_provider=provider, stt_provider=None)
    await manager.handle_text("")
    await manager.handle_text("   ")

    assert len(received) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_input.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement input providers and manager**

```python
# shannon/input/__init__.py
# (empty)

# shannon/input/providers/__init__.py
# (empty)

# shannon/input/providers/base.py
"""Abstract base for STT providers."""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class STTProvider(ABC):
    """Abstract base class for speech-to-text providers."""

    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Transcribe audio bytes to text."""
        ...

    @abstractmethod
    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
        """Stream transcription from an audio stream."""
        ...
```

```python
# shannon/input/providers/text.py
"""Text input provider — reads from stdin."""

import asyncio
import sys


class TextInputProvider:
    """Provides text input from stdin."""

    async def read_line(self) -> str | None:
        """Read a line from stdin asynchronously."""
        loop = asyncio.get_event_loop()
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return None
        return line.strip()
```

```python
# shannon/input/providers/whisper.py
"""Whisper STT provider using faster-whisper."""

from typing import AsyncIterator

from shannon.input.providers.base import STTProvider


class WhisperProvider(STTProvider):
    """Speech-to-text using faster-whisper (local)."""

    def __init__(self, model: str = "base.en", device: str = "auto") -> None:
        self._model_name = model
        self._device = device
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            compute = "cuda" if self._device == "auto" else self._device
            try:
                self._model = WhisperModel(self._model_name, device=compute)
            except Exception:
                self._model = WhisperModel(self._model_name, device="cpu")

    async def transcribe(self, audio: bytes) -> str:
        import tempfile
        import asyncio
        self._ensure_model()

        def _do_transcribe():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
                f.write(audio)
                f.flush()
                segments, _ = self._model.transcribe(f.name)
                return " ".join(seg.text for seg in segments).strip()

        return await asyncio.get_event_loop().run_in_executor(None, _do_transcribe)

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
        """Accumulate audio chunks and transcribe."""
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            chunks.append(chunk)
        if chunks:
            full_audio = b"".join(chunks)
            text = await self.transcribe(full_audio)
            if text:
                yield text
```

```python
# shannon/input/manager.py
"""Input manager — bridges text and STT input to the event bus."""

import asyncio
import logging

from shannon.bus import EventBus
from shannon.events import UserInput
from shannon.input.providers.base import STTProvider
from shannon.input.providers.text import TextInputProvider

logger = logging.getLogger(__name__)


class InputManager:
    """Manages input sources and emits UserInput events."""

    def __init__(
        self,
        bus: EventBus,
        text_provider: TextInputProvider | None = None,
        stt_provider: STTProvider | None = None,
    ) -> None:
        self._bus = bus
        self._text_provider = text_provider
        self._stt_provider = stt_provider
        self._speech_mode = False

    async def handle_text(self, text: str) -> None:
        """Handle a text input string."""
        text = text.strip()
        if not text:
            return
        await self._bus.publish(UserInput(text=text, source="text"))

    async def handle_audio(self, audio: bytes) -> None:
        """Handle audio input via STT."""
        if not self._stt_provider:
            logger.warning("No STT provider configured")
            return
        text = await self._stt_provider.transcribe(audio)
        if text.strip():
            await self._bus.publish(UserInput(text=text.strip(), source="voice"))

    async def run_text_loop(self) -> None:
        """Run the stdin text input loop."""
        if not self._text_provider:
            return
        while True:
            line = await self._text_provider.read_line()
            if line is None:
                break
            await self.handle_text(line)

    def set_speech_mode(self, enabled: bool) -> None:
        """Toggle speech input mode."""
        self._speech_mode = enabled
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_input.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/input/ tests/test_input.py
git commit -m "feat: input system with text and whisper STT providers"
```

---

### Task 8: Output System (TTS + VTuber)

**Files:**
- Create: `shannon/output/__init__.py`
- Create: `shannon/output/manager.py`
- Create: `shannon/output/providers/__init__.py`
- Create: `shannon/output/providers/tts/__init__.py`
- Create: `shannon/output/providers/tts/base.py`
- Create: `shannon/output/providers/tts/piper.py`
- Create: `shannon/output/providers/vtuber/__init__.py`
- Create: `shannon/output/providers/vtuber/base.py`
- Create: `shannon/output/providers/vtuber/vtube_studio.py`
- Create: `tests/test_output.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_output.py
from shannon.bus import EventBus
from shannon.output.manager import OutputManager
from shannon.output.providers.tts.base import TTSProvider, AudioChunk
from shannon.output.providers.vtuber.base import VTuberProvider
from shannon.events import LLMResponse, SpeechStart, SpeechEnd, ExpressionChange


def test_tts_provider_is_abstract():
    try:
        TTSProvider()  # type: ignore
        assert False
    except TypeError:
        pass


def test_vtuber_provider_is_abstract():
    try:
        VTuberProvider()  # type: ignore
        assert False
    except TypeError:
        pass


def test_audio_chunk():
    chunk = AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)
    assert chunk.sample_rate == 22050
    assert len(chunk.data) == 100


class FakeTTS(TTSProvider):
    def __init__(self):
        self.last_text = ""

    async def synthesize(self, text):
        self.last_text = text
        return AudioChunk(data=b"\x00" * 100, sample_rate=22050, channels=1)

    async def stream_synthesize(self, text):
        yield AudioChunk(data=b"\x00" * 50, sample_rate=22050, channels=1)

    async def get_phonemes(self, text):
        return list(text[:5])


class FakeVTuber(VTuberProvider):
    def __init__(self):
        self.expressions = []
        self.speaking = False

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def set_expression(self, name, intensity):
        self.expressions.append((name, intensity))

    async def start_speaking(self, phonemes=None):
        self.speaking = True

    async def stop_speaking(self):
        self.speaking = False

    async def set_idle_animation(self, name):
        pass


async def test_output_manager_handles_response_text_mode():
    bus = EventBus()
    tts = FakeTTS()
    vtuber = FakeVTuber()

    manager = OutputManager(bus, tts_provider=tts, vtuber_provider=vtuber, speech_output=False)
    await manager.start()

    printed = []
    original_print = __builtins__["print"] if isinstance(__builtins__, dict) else __builtins__.print

    await bus.publish(LLMResponse(
        text="Hello world!",
        expressions=[{"name": "happy", "intensity": 0.8}],
        actions=[],
        mood="cheerful",
    ))

    # In text mode, TTS should not be called
    assert tts.last_text == ""


async def test_output_manager_handles_response_speech_mode():
    bus = EventBus()
    tts = FakeTTS()
    vtuber = FakeVTuber()

    speech_events = []
    async def capture_speech_start(event):
        speech_events.append(("start", event))
    async def capture_speech_end(event):
        speech_events.append(("end", event))

    bus.subscribe(SpeechStart, capture_speech_start)
    bus.subscribe(SpeechEnd, capture_speech_end)

    manager = OutputManager(bus, tts_provider=tts, vtuber_provider=vtuber, speech_output=True)
    await manager.start()

    await bus.publish(LLMResponse(
        text="Hello!",
        expressions=[],
        actions=[],
        mood="neutral",
    ))

    assert tts.last_text == "Hello!"
    assert len(speech_events) == 2
    assert speech_events[0][0] == "start"
    assert speech_events[1][0] == "end"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_output.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement TTS base and VTuber base**

```python
# shannon/output/__init__.py
# (empty)

# shannon/output/providers/__init__.py
# (empty)

# shannon/output/providers/tts/__init__.py
# (empty)

# shannon/output/providers/tts/base.py
"""Abstract base for TTS providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class AudioChunk:
    """A chunk of audio data."""
    data: bytes
    sample_rate: int
    channels: int = 1


class TTSProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @abstractmethod
    async def synthesize(self, text: str) -> AudioChunk:
        """Synthesize text to audio."""
        ...

    @abstractmethod
    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Stream synthesized audio chunks."""
        ...

    @abstractmethod
    async def get_phonemes(self, text: str) -> list[str]:
        """Extract phonemes from text for lip sync."""
        ...
```

```python
# shannon/output/providers/vtuber/__init__.py
# (empty)

# shannon/output/providers/vtuber/base.py
"""Abstract base for VTuber model providers."""

from abc import ABC, abstractmethod


class VTuberProvider(ABC):
    """Abstract base class for VTuber model control."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the VTuber application."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the VTuber application."""
        ...

    @abstractmethod
    async def set_expression(self, name: str, intensity: float) -> None:
        """Set a facial expression."""
        ...

    @abstractmethod
    async def start_speaking(self, phonemes: list[str] | None = None) -> None:
        """Signal that speech has started (for lip sync)."""
        ...

    @abstractmethod
    async def stop_speaking(self) -> None:
        """Signal that speech has stopped."""
        ...

    @abstractmethod
    async def set_idle_animation(self, name: str) -> None:
        """Set the idle animation."""
        ...
```

- [ ] **Step 4: Implement OutputManager**

```python
# shannon/output/manager.py
"""Output manager — routes LLM responses to TTS and VTuber."""

import logging

from shannon.bus import EventBus
from shannon.events import ExpressionChange, LLMResponse, SpeechEnd, SpeechStart
from shannon.output.providers.tts.base import TTSProvider
from shannon.output.providers.vtuber.base import VTuberProvider

logger = logging.getLogger(__name__)


class OutputManager:
    """Routes LLM responses to TTS and VTuber providers."""

    def __init__(
        self,
        bus: EventBus,
        tts_provider: TTSProvider | None = None,
        vtuber_provider: VTuberProvider | None = None,
        speech_output: bool = False,
    ) -> None:
        self._bus = bus
        self._tts = tts_provider
        self._vtuber = vtuber_provider
        self._speech_output = speech_output

    async def start(self) -> None:
        """Subscribe to events."""
        self._bus.subscribe(LLMResponse, self._on_llm_response)
        self._bus.subscribe(ExpressionChange, self._on_expression_change)
        if self._vtuber:
            await self._vtuber.connect()

    async def stop(self) -> None:
        """Clean up."""
        if self._vtuber:
            await self._vtuber.disconnect()

    async def _on_llm_response(self, event: LLMResponse) -> None:
        """Handle LLM response — display text and/or speak."""
        if not event.text:
            return

        if self._speech_output and self._tts:
            # Speech mode: synthesize and play
            phonemes = await self._tts.get_phonemes(event.text)
            audio = await self._tts.synthesize(event.text)

            duration = len(audio.data) / (audio.sample_rate * audio.channels * 2)  # 16-bit
            await self._bus.publish(SpeechStart(duration=duration, phonemes=phonemes))

            # Play audio (actual playback handled by audio subsystem)
            self._play_audio(audio)

            await self._bus.publish(SpeechEnd())
        else:
            # Text mode: print to stdout
            print(f"\n{event.text}")

    async def _on_expression_change(self, event: ExpressionChange) -> None:
        """Forward expression changes to VTuber provider."""
        if self._vtuber:
            await self._vtuber.set_expression(event.name, event.intensity)

    def _play_audio(self, audio) -> None:
        """Play audio data. Placeholder — needs platform-specific audio output."""
        logger.debug("Playing audio: %d bytes at %d Hz", len(audio.data), audio.sample_rate)

    def set_speech_output(self, enabled: bool) -> None:
        """Toggle speech output mode."""
        self._speech_output = enabled
```

- [ ] **Step 5: Implement PiperProvider**

```python
# shannon/output/providers/tts/piper.py
"""Piper TTS provider — local text-to-speech."""

import asyncio
import logging
from typing import AsyncIterator

from shannon.output.providers.tts.base import AudioChunk, TTSProvider

logger = logging.getLogger(__name__)


class PiperProvider(TTSProvider):
    """Local TTS using piper-tts."""

    def __init__(self, model: str = "en_US-lessac-medium", rate: float = 1.0) -> None:
        self._model_name = model
        self._rate = rate
        self._voice = None

    def _ensure_voice(self):
        if self._voice is None:
            try:
                import piper
                self._voice = piper.PiperVoice.load(self._model_name)
            except Exception as e:
                logger.error("Failed to load Piper voice '%s': %s", self._model_name, e)
                raise

    async def synthesize(self, text: str) -> AudioChunk:
        self._ensure_voice()

        def _do_synth():
            import io
            import wave
            audio_bytes = io.BytesIO()
            with wave.open(audio_bytes, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(22050)
                for chunk in self._voice.synthesize_stream_raw(text):
                    wav.writeframes(chunk)
            return audio_bytes.getvalue()

        data = await asyncio.get_event_loop().run_in_executor(None, _do_synth)
        return AudioChunk(data=data, sample_rate=22050, channels=1)

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        self._ensure_voice()

        def _generate():
            chunks = []
            for chunk in self._voice.synthesize_stream_raw(text):
                chunks.append(chunk)
            return chunks

        chunks = await asyncio.get_event_loop().run_in_executor(None, _generate)
        for chunk in chunks:
            yield AudioChunk(data=chunk, sample_rate=22050, channels=1)

    async def get_phonemes(self, text: str) -> list[str]:
        # Piper doesn't easily expose phonemes — return placeholder
        # A future improvement could use espeak-ng for phoneme extraction
        return []
```

- [ ] **Step 6: Implement VTubeStudioProvider**

```python
# shannon/output/providers/vtuber/vtube_studio.py
"""VTube Studio provider — control Live2D model via VTS API."""

import asyncio
import json
import logging
import uuid

from shannon.output.providers.vtuber.base import VTuberProvider

logger = logging.getLogger(__name__)


class VTubeStudioProvider(VTuberProvider):
    """Control a VTuber model via the VTube Studio WebSocket API."""

    def __init__(self, host: str = "localhost", port: int = 8001) -> None:
        self._host = host
        self._port = port
        self._ws = None
        self._authenticated = False
        self._plugin_name = "Shannon AI VTuber"
        self._plugin_developer = "Shannon"

    async def connect(self) -> None:
        try:
            import websockets
            uri = f"ws://{self._host}:{self._port}"
            self._ws = await websockets.connect(uri)
            await self._authenticate()
            logger.info("Connected to VTube Studio at %s", uri)
        except Exception as e:
            logger.warning("Could not connect to VTube Studio: %s", e)
            self._ws = None

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _authenticate(self) -> None:
        """Authenticate with VTube Studio API."""
        if not self._ws:
            return

        # Request auth token
        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": str(uuid.uuid4()),
            "messageType": "AuthenticationTokenRequest",
            "data": {
                "pluginName": self._plugin_name,
                "pluginDeveloper": self._plugin_developer,
            },
        }
        await self._ws.send(json.dumps(request))
        response = json.loads(await self._ws.recv())

        if "data" in response and "authenticationToken" in response["data"]:
            token = response["data"]["authenticationToken"]
            # Authenticate with token
            auth_request = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": str(uuid.uuid4()),
                "messageType": "AuthenticationRequest",
                "data": {
                    "pluginName": self._plugin_name,
                    "pluginDeveloper": self._plugin_developer,
                    "authenticationToken": token,
                },
            }
            await self._ws.send(json.dumps(auth_request))
            auth_response = json.loads(await self._ws.recv())
            self._authenticated = auth_response.get("data", {}).get("authenticated", False)

    async def _send_request(self, message_type: str, data: dict) -> dict:
        """Send a request to VTube Studio and return the response."""
        if not self._ws or not self._authenticated:
            return {}
        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": str(uuid.uuid4()),
            "messageType": message_type,
            "data": data,
        }
        await self._ws.send(json.dumps(request))
        return json.loads(await self._ws.recv())

    async def set_expression(self, name: str, intensity: float) -> None:
        # VTS uses "expression files" — map our expression names to .exp3.json files
        # This is model-specific; users configure expression file names in their model
        await self._send_request("ExpressionActivationRequest", {
            "expressionFile": f"{name}.exp3.json",
            "active": intensity > 0.1,
        })

    async def start_speaking(self, phonemes: list[str] | None = None) -> None:
        # VTS mouth tracking — inject mouth open parameter
        await self._send_request("InjectParameterDataRequest", {
            "parameterValues": [
                {"id": "MouthOpen", "value": 1.0},
            ],
        })

    async def stop_speaking(self) -> None:
        await self._send_request("InjectParameterDataRequest", {
            "parameterValues": [
                {"id": "MouthOpen", "value": 0.0},
            ],
        })

    async def set_idle_animation(self, name: str) -> None:
        logger.debug("Set idle animation: %s (VTS handles idle natively)", name)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_output.py -v`
Expected: All 5 tests PASS

- [ ] **Step 8: Commit**

```bash
git add shannon/output/ tests/test_output.py
git commit -m "feat: output system with TTS, VTuber providers, and output manager"
```

---

### Task 9: Vision System

**Files:**
- Create: `shannon/vision/__init__.py`
- Create: `shannon/vision/manager.py`
- Create: `shannon/vision/providers/__init__.py`
- Create: `shannon/vision/providers/base.py`
- Create: `shannon/vision/providers/screen.py`
- Create: `shannon/vision/providers/webcam.py`
- Create: `tests/test_vision.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vision.py
import asyncio
from shannon.bus import EventBus
from shannon.vision.manager import VisionManager
from shannon.vision.providers.base import VisionProvider
from shannon.events import VisionFrame


def test_vision_provider_is_abstract():
    try:
        VisionProvider()  # type: ignore
        assert False
    except TypeError:
        pass


class FakeScreenCapture(VisionProvider):
    def __init__(self):
        self.capture_count = 0

    async def capture(self) -> bytes:
        self.capture_count += 1
        return b"\x89PNG_fake_screen"

    def source_name(self) -> str:
        return "screen"


class FakeWebcamCapture(VisionProvider):
    async def capture(self) -> bytes:
        return b"\x89PNG_fake_webcam"

    def source_name(self) -> str:
        return "cam"


async def test_vision_manager_emits_frames():
    bus = EventBus()
    screen = FakeScreenCapture()
    frames = []

    async def capture(event: VisionFrame):
        frames.append(event)

    bus.subscribe(VisionFrame, capture)

    manager = VisionManager(bus, providers=[screen], interval_seconds=0.05)
    task = asyncio.create_task(manager.run())

    await asyncio.sleep(0.15)
    manager.stop()
    await task

    assert len(frames) >= 2
    assert frames[0].source == "screen"
    assert frames[0].image == b"\x89PNG_fake_screen"


async def test_vision_manager_multiple_sources():
    bus = EventBus()
    screen = FakeScreenCapture()
    webcam = FakeWebcamCapture()
    frames = []

    async def capture(event: VisionFrame):
        frames.append(event)

    bus.subscribe(VisionFrame, capture)

    manager = VisionManager(bus, providers=[screen, webcam], interval_seconds=0.05)
    task = asyncio.create_task(manager.run())

    await asyncio.sleep(0.15)
    manager.stop()
    await task

    sources = {f.source for f in frames}
    assert "screen" in sources
    assert "cam" in sources
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_vision.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement vision providers and manager**

```python
# shannon/vision/__init__.py
# (empty)

# shannon/vision/providers/__init__.py
# (empty)

# shannon/vision/providers/base.py
"""Abstract base for vision providers."""

from abc import ABC, abstractmethod


class VisionProvider(ABC):
    """Abstract base class for vision capture providers."""

    @abstractmethod
    async def capture(self) -> bytes:
        """Capture an image and return as PNG bytes."""
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier (e.g. 'screen', 'cam')."""
        ...
```

```python
# shannon/vision/providers/screen.py
"""Screen capture provider using mss."""

import asyncio
import io
import logging

from shannon.vision.providers.base import VisionProvider

logger = logging.getLogger(__name__)


class ScreenCapture(VisionProvider):
    """Capture the screen using mss."""

    def __init__(self) -> None:
        self._sct = None

    def _ensure_sct(self):
        if self._sct is None:
            import mss
            self._sct = mss.mss()

    async def capture(self) -> bytes:
        self._ensure_sct()

        def _do_capture():
            monitor = self._sct.monitors[0]  # All monitors combined
            screenshot = self._sct.grab(monitor)
            # Convert to PNG bytes
            from mss.tools import to_png
            return to_png(screenshot.rgb, screenshot.size)

        return await asyncio.get_event_loop().run_in_executor(None, _do_capture)

    def source_name(self) -> str:
        return "screen"
```

```python
# shannon/vision/providers/webcam.py
"""Webcam capture provider using opencv."""

import asyncio
import logging

from shannon.vision.providers.base import VisionProvider

logger = logging.getLogger(__name__)


class WebcamCapture(VisionProvider):
    """Capture from webcam using OpenCV."""

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index
        self._cap = None

    def _ensure_cap(self):
        if self._cap is None:
            import cv2
            self._cap = cv2.VideoCapture(self._device_index)
            if not self._cap.isOpened():
                logger.error("Could not open webcam device %d", self._device_index)

    async def capture(self) -> bytes:
        self._ensure_cap()

        def _do_capture():
            import cv2
            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Failed to capture webcam frame")
                return b""
            _, png_data = cv2.imencode(".png", frame)
            return png_data.tobytes()

        return await asyncio.get_event_loop().run_in_executor(None, _do_capture)

    def source_name(self) -> str:
        return "cam"

    def release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
```

```python
# shannon/vision/manager.py
"""Vision manager — periodic capture loop emitting VisionFrame events."""

import asyncio
import logging

from shannon.bus import EventBus
from shannon.events import VisionFrame
from shannon.vision.providers.base import VisionProvider

logger = logging.getLogger(__name__)


class VisionManager:
    """Captures images from vision providers on an interval."""

    def __init__(
        self,
        bus: EventBus,
        providers: list[VisionProvider],
        interval_seconds: float = 5.0,
    ) -> None:
        self._bus = bus
        self._providers = providers
        self._interval = interval_seconds
        self._running = False

    async def run(self) -> None:
        """Run the capture loop."""
        self._running = True
        while self._running:
            for provider in self._providers:
                try:
                    image = await provider.capture()
                    if image:
                        await self._bus.publish(VisionFrame(
                            image=image,
                            source=provider.source_name(),
                        ))
                except Exception as e:
                    logger.error("Vision capture error (%s): %s", provider.source_name(), e)
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        """Stop the capture loop."""
        self._running = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_vision.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/vision/ tests/test_vision.py
git commit -m "feat: vision system with screen and webcam capture providers"
```

---

### Task 10: Action System + Safety Pipeline

**Files:**
- Create: `shannon/actions/__init__.py`
- Create: `shannon/actions/manager.py`
- Create: `shannon/actions/providers/__init__.py`
- Create: `shannon/actions/providers/base.py`
- Create: `shannon/actions/providers/shell.py`
- Create: `shannon/actions/providers/browser.py`
- Create: `shannon/actions/providers/mouse.py`
- Create: `shannon/actions/providers/keyboard.py`
- Create: `tests/test_actions.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_actions.py
import asyncio
from unittest.mock import patch, AsyncMock
from shannon.bus import EventBus
from shannon.actions.manager import ActionManager
from shannon.actions.providers.base import ActionProvider
from shannon.actions.providers.shell import ShellAction
from shannon.config import ShannonConfig
from shannon.events import ActionRequest, ActionResult


def test_action_provider_is_abstract():
    try:
        ActionProvider()  # type: ignore
        assert False
    except TypeError:
        pass


class TestShellAction:
    def setup_method(self):
        config = ShannonConfig()
        self.provider = ShellAction(config.actions.shell)

    def test_validate_allowed(self):
        assert self.provider.validate({"command": "ls -la"}) is True

    def test_validate_blocked(self):
        assert self.provider.validate({"command": "rm -rf /"}) is False
        assert self.provider.validate({"command": "sudo apt install"}) is False

    def test_capabilities(self):
        caps = self.provider.get_capabilities()
        assert "shell" in caps


class TestActionManager:
    def setup_method(self):
        self.bus = EventBus()
        self.config = ShannonConfig()
        # Set shell to allow mode for testing
        self.config.actions.shell.approval = "allow"
        self.shell = ShellAction(self.config.actions.shell)
        self.manager = ActionManager(self.bus, {"shell": self.shell}, self.config)

    async def test_executes_allowed_action(self):
        results = []
        async def capture(event: ActionResult):
            results.append(event)
        self.bus.subscribe(ActionResult, capture)

        await self.manager.start()
        await self.bus.publish(ActionRequest(action_type="shell", params={"command": "echo hello"}))

        assert len(results) == 1
        assert results[0].success is True
        assert "hello" in results[0].output

    async def test_rejects_blocked_command(self):
        results = []
        async def capture(event: ActionResult):
            results.append(event)
        self.bus.subscribe(ActionResult, capture)

        await self.manager.start()
        await self.bus.publish(ActionRequest(action_type="shell", params={"command": "rm -rf /"}))

        assert len(results) == 1
        assert results[0].success is False
        assert "blocked" in results[0].error.lower() or "denied" in results[0].error.lower()

    async def test_rejects_unknown_action_type(self):
        results = []
        async def capture(event: ActionResult):
            results.append(event)
        self.bus.subscribe(ActionResult, capture)

        await self.manager.start()
        await self.bus.publish(ActionRequest(action_type="unknown", params={}))

        assert len(results) == 1
        assert results[0].success is False

    async def test_rejects_disabled_action(self):
        self.config.actions.shell.enabled = False
        results = []
        async def capture(event: ActionResult):
            results.append(event)
        self.bus.subscribe(ActionResult, capture)

        await self.manager.start()
        await self.bus.publish(ActionRequest(action_type="shell", params={"command": "echo test"}))

        assert len(results) == 1
        assert results[0].success is False

    async def test_deny_mode_rejects(self):
        self.config.actions.shell.approval = "deny"
        results = []
        async def capture(event: ActionResult):
            results.append(event)
        self.bus.subscribe(ActionResult, capture)

        await self.manager.start()
        await self.bus.publish(ActionRequest(action_type="shell", params={"command": "echo test"}))

        assert len(results) == 1
        assert results[0].success is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_actions.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ActionProvider base**

```python
# shannon/actions/__init__.py
# (empty)

# shannon/actions/providers/__init__.py
# (empty)

# shannon/actions/providers/base.py
"""Abstract base for action providers."""

from abc import ABC, abstractmethod
from typing import Any


class ActionProvider(ABC):
    """Abstract base class for computer action providers."""

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> tuple[bool, str, str]:
        """Execute an action. Returns (success, output, error)."""
        ...

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """Return list of capability identifiers."""
        ...

    @abstractmethod
    def validate(self, params: dict[str, Any]) -> bool:
        """Validate whether this action is allowed."""
        ...
```

- [ ] **Step 4: Implement ShellAction**

```python
# shannon/actions/providers/shell.py
"""Shell command action provider."""

import asyncio
import logging
from typing import Any

from shannon.actions.providers.base import ActionProvider
from shannon.config import ShellActionConfig

logger = logging.getLogger(__name__)


class ShellAction(ActionProvider):
    """Execute shell commands via subprocess."""

    def __init__(self, config: ShellActionConfig) -> None:
        self._config = config

    def get_capabilities(self) -> list[str]:
        return ["shell"]

    def validate(self, params: dict[str, Any]) -> bool:
        command = params.get("command", "")
        # Check blocklist
        for blocked in self._config.blocklist:
            if blocked in command:
                logger.warning("Blocked command: %s (matches: %s)", command, blocked)
                return False
        # Check allowlist
        if self._config.allowlist != ["*"]:
            allowed = any(cmd in command for cmd in self._config.allowlist)
            if not allowed:
                return False
        return True

    async def execute(self, params: dict[str, Any]) -> tuple[bool, str, str]:
        command = params.get("command", "")
        if not command:
            return False, "", "No command provided"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.timeout_seconds,
            )
            success = proc.returncode == 0
            return success, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except asyncio.TimeoutError:
            return False, "", f"Command timed out after {self._config.timeout_seconds}s"
        except Exception as e:
            return False, "", str(e)
```

- [ ] **Step 5: Implement BrowserAction, MouseAction, KeyboardAction**

```python
# shannon/actions/providers/browser.py
"""Browser automation action provider using Playwright."""

import asyncio
import logging
from typing import Any

from shannon.actions.providers.base import ActionProvider
from shannon.config import BrowserActionConfig

logger = logging.getLogger(__name__)


class BrowserAction(ActionProvider):
    """Browser automation via Playwright."""

    def __init__(self, config: BrowserActionConfig) -> None:
        self._config = config
        self._browser = None
        self._page = None

    def get_capabilities(self) -> list[str]:
        return ["browser"]

    def validate(self, params: dict[str, Any]) -> bool:
        url = params.get("url", "")
        if url and self._config.blocked_domains:
            from urllib.parse import urlparse
            domain = urlparse(url).hostname or ""
            if any(blocked in domain for blocked in self._config.blocked_domains):
                return False
        return True

    async def _ensure_browser(self):
        if self._browser is None:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=self._config.headless)
            self._page = await self._browser.new_page()

    async def execute(self, params: dict[str, Any]) -> tuple[bool, str, str]:
        try:
            await self._ensure_browser()
            action = params.get("action", "navigate")

            if action == "navigate":
                url = params.get("url", "")
                await self._page.goto(url)
                return True, f"Navigated to {url}", ""
            elif action == "click":
                selector = params.get("selector", "")
                await self._page.click(selector)
                return True, f"Clicked {selector}", ""
            elif action == "type":
                selector = params.get("selector", "")
                text = params.get("text", "")
                await self._page.fill(selector, text)
                return True, f"Typed into {selector}", ""
            elif action == "screenshot":
                screenshot = await self._page.screenshot()
                return True, f"Screenshot taken ({len(screenshot)} bytes)", ""
            else:
                return False, "", f"Unknown browser action: {action}"
        except Exception as e:
            return False, "", str(e)
```

```python
# shannon/actions/providers/mouse.py
"""Mouse control action provider using pyautogui."""

import asyncio
import logging
import time
from typing import Any

from shannon.actions.providers.base import ActionProvider
from shannon.config import MouseActionConfig

logger = logging.getLogger(__name__)


class MouseAction(ActionProvider):
    """Mouse control via pyautogui."""

    def __init__(self, config: MouseActionConfig) -> None:
        self._config = config
        self._last_action_time = 0.0

    def get_capabilities(self) -> list[str]:
        return ["mouse"]

    def validate(self, params: dict[str, Any]) -> bool:
        # Rate limiting
        now = time.time()
        if now - self._last_action_time < (1.0 / self._config.rate_limit):
            return False
        return True

    async def execute(self, params: dict[str, Any]) -> tuple[bool, str, str]:
        try:
            import pyautogui
            x = params.get("x", 0)
            y = params.get("y", 0)
            click = params.get("click", False)
            button = params.get("button", "left")

            def _do():
                pyautogui.moveTo(x, y)
                if click:
                    pyautogui.click(x, y, button=button)

            await asyncio.get_event_loop().run_in_executor(None, _do)
            self._last_action_time = time.time()

            action_desc = f"Moved to ({x}, {y})"
            if click:
                action_desc += f" and {button}-clicked"
            return True, action_desc, ""
        except Exception as e:
            return False, "", str(e)
```

```python
# shannon/actions/providers/keyboard.py
"""Keyboard control action provider using pyautogui."""

import asyncio
import logging
import time
from typing import Any

from shannon.actions.providers.base import ActionProvider
from shannon.config import KeyboardActionConfig

logger = logging.getLogger(__name__)


class KeyboardAction(ActionProvider):
    """Keyboard control via pyautogui."""

    def __init__(self, config: KeyboardActionConfig) -> None:
        self._config = config
        self._last_action_time = 0.0

    def get_capabilities(self) -> list[str]:
        return ["keyboard"]

    def validate(self, params: dict[str, Any]) -> bool:
        keys = params.get("keys", "")
        is_hotkey = params.get("is_hotkey", False)
        # Check blocked combos
        if is_hotkey:
            normalized = keys.lower().replace(" ", "")
            for blocked in self._config.blocked_combos:
                if normalized == blocked.lower().replace(" ", ""):
                    logger.warning("Blocked key combo: %s", keys)
                    return False
        # Rate limiting
        now = time.time()
        if now - self._last_action_time < (1.0 / self._config.rate_limit):
            return False
        return True

    async def execute(self, params: dict[str, Any]) -> tuple[bool, str, str]:
        try:
            import pyautogui
            keys = params.get("keys", "")
            is_hotkey = params.get("is_hotkey", False)

            def _do():
                if is_hotkey:
                    key_list = [k.strip() for k in keys.split("+")]
                    pyautogui.hotkey(*key_list)
                else:
                    pyautogui.typewrite(keys, interval=0.02)

            await asyncio.get_event_loop().run_in_executor(None, _do)
            self._last_action_time = time.time()

            if is_hotkey:
                return True, f"Pressed hotkey: {keys}", ""
            else:
                return True, f"Typed: {keys}", ""
        except Exception as e:
            return False, "", str(e)
```

- [ ] **Step 6: Implement ActionManager with safety pipeline**

```python
# shannon/actions/manager.py
"""Action manager — safety pipeline and action dispatch."""

import asyncio
import logging
from typing import Any

from shannon.actions.providers.base import ActionProvider
from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import ActionRequest, ActionResult

logger = logging.getLogger(__name__)


class ActionManager:
    """Manages action execution with a multi-gate safety pipeline."""

    def __init__(
        self,
        bus: EventBus,
        providers: dict[str, ActionProvider],
        config: ShannonConfig,
    ) -> None:
        self._bus = bus
        self._providers = providers
        self._config = config

    async def start(self) -> None:
        """Subscribe to action request events."""
        self._bus.subscribe(ActionRequest, self._on_action_request)

    async def _on_action_request(self, event: ActionRequest) -> None:
        """Process an action request through the safety pipeline."""
        result = await self._execute_with_safety(event.action_type, event.params)
        await self._bus.publish(result)

    async def _execute_with_safety(self, action_type: str, params: dict[str, Any]) -> ActionResult:
        """Five-gate safety pipeline."""

        # Gate 1: Type validation
        provider = self._providers.get(action_type)
        if not provider:
            logger.warning("Unknown action type: %s", action_type)
            return ActionResult(
                action_type=action_type,
                success=False,
                error=f"Unknown action type: {action_type}",
            )

        # Gate 2: Enabled check
        action_config = getattr(self._config.actions, action_type, None)
        if action_config and not action_config.enabled:
            return ActionResult(
                action_type=action_type,
                success=False,
                error=f"Action type '{action_type}' is disabled",
            )

        # Gate 3: Provider validation
        if not provider.validate(params):
            return ActionResult(
                action_type=action_type,
                success=False,
                error=f"Action denied by validation: {action_type} with params {params}",
            )

        # Gate 4: Approval check
        approval = action_config.approval if action_config else "confirm"
        if approval == "deny":
            return ActionResult(
                action_type=action_type,
                success=False,
                error=f"Action type '{action_type}' is set to deny",
            )
        elif approval == "confirm":
            approved = await self._prompt_user(action_type, params)
            if not approved:
                return ActionResult(
                    action_type=action_type,
                    success=False,
                    error="Action denied by user",
                )

        # Gate 5: Execute
        try:
            success, output, error = await provider.execute(params)
            return ActionResult(
                action_type=action_type,
                success=success,
                output=output,
                error=error,
            )
        except Exception as e:
            logger.error("Action execution error: %s", e)
            return ActionResult(
                action_type=action_type,
                success=False,
                error=str(e),
            )

    async def _prompt_user(self, action_type: str, params: dict[str, Any]) -> bool:
        """Prompt the user for approval in the terminal."""
        desc = self._describe_action(action_type, params)
        print(f"\n[Shannon wants to: {desc}]")

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: input("Allow? (y/n): "))
        return response.strip().lower() in ("y", "yes")

    def _describe_action(self, action_type: str, params: dict[str, Any]) -> str:
        """Human-readable description of an action."""
        if action_type == "shell":
            return f"Run command: {params.get('command', '?')}"
        elif action_type == "browser":
            return f"Browser: {params.get('action', '?')} {params.get('url', '')}"
        elif action_type == "mouse":
            click = "click" if params.get("click") else "move"
            return f"Mouse {click} at ({params.get('x')}, {params.get('y')})"
        elif action_type == "keyboard":
            return f"Type: {params.get('keys', '?')}"
        return f"{action_type}: {params}"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_actions.py -v`
Expected: All 7 tests PASS

- [ ] **Step 8: Commit**

```bash
git add shannon/actions/ tests/test_actions.py
git commit -m "feat: action system with safety pipeline and shell/browser/mouse/keyboard providers"
```

---

### Task 11: Autonomy Loop

**Files:**
- Create: `shannon/autonomy/__init__.py`
- Create: `shannon/autonomy/loop.py`
- Create: `tests/test_autonomy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_autonomy.py
import asyncio
import time
from shannon.bus import EventBus
from shannon.autonomy.loop import AutonomyLoop
from shannon.config import ShannonConfig
from shannon.events import VisionFrame, AutonomousTrigger


async def test_autonomy_triggers_on_idle():
    bus = EventBus()
    config = ShannonConfig()
    config.autonomy.idle_timeout_seconds = 0.1
    config.autonomy.cooldown_seconds = 0

    triggers = []
    async def capture(event: AutonomousTrigger):
        triggers.append(event)
    bus.subscribe(AutonomousTrigger, capture)

    loop = AutonomyLoop(bus, config)
    task = asyncio.create_task(loop.run())

    await asyncio.sleep(0.3)
    loop.stop()
    await task

    assert len(triggers) >= 1
    assert triggers[0].reason == "idle_timeout"


async def test_autonomy_triggers_on_screen_change():
    bus = EventBus()
    config = ShannonConfig()
    config.autonomy.cooldown_seconds = 0

    triggers = []
    async def capture(event: AutonomousTrigger):
        triggers.append(event)
    bus.subscribe(AutonomousTrigger, capture)

    loop = AutonomyLoop(bus, config)
    task = asyncio.create_task(loop.run())

    # Simulate two very different vision frames
    await bus.publish(VisionFrame(image=b"\x00" * 1000, source="screen"))
    await asyncio.sleep(0.05)
    await bus.publish(VisionFrame(image=b"\xff" * 1000, source="screen"))
    await asyncio.sleep(0.1)

    loop.stop()
    await task

    screen_triggers = [t for t in triggers if t.reason == "screen_change"]
    assert len(screen_triggers) >= 1


async def test_autonomy_respects_cooldown():
    bus = EventBus()
    config = ShannonConfig()
    config.autonomy.idle_timeout_seconds = 0.05
    config.autonomy.cooldown_seconds = 10  # Long cooldown

    triggers = []
    async def capture(event: AutonomousTrigger):
        triggers.append(event)
    bus.subscribe(AutonomousTrigger, capture)

    loop = AutonomyLoop(bus, config)
    task = asyncio.create_task(loop.run())

    await asyncio.sleep(0.2)
    loop.stop()
    await task

    # Should only trigger once due to cooldown
    assert len(triggers) <= 1


async def test_autonomy_disabled():
    bus = EventBus()
    config = ShannonConfig()
    config.autonomy.enabled = False

    triggers = []
    async def capture(event: AutonomousTrigger):
        triggers.append(event)
    bus.subscribe(AutonomousTrigger, capture)

    loop = AutonomyLoop(bus, config)
    task = asyncio.create_task(loop.run())

    await asyncio.sleep(0.1)
    loop.stop()
    await task

    assert len(triggers) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_autonomy.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement AutonomyLoop**

```python
# shannon/autonomy/__init__.py
# (empty)

# shannon/autonomy/loop.py
"""Autonomy loop — decides when Shannon should react unprompted."""

import asyncio
import hashlib
import logging
import time

from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import AutonomousTrigger, UserInput, VisionFrame

logger = logging.getLogger(__name__)


class AutonomyLoop:
    """Background loop that triggers autonomous reactions."""

    def __init__(self, bus: EventBus, config: ShannonConfig) -> None:
        self._bus = bus
        self._config = config
        self._running = False
        self._last_trigger_time = 0.0
        self._last_input_time = time.time()
        self._last_frame_hash: str = ""
        self._latest_frame: VisionFrame | None = None

    async def run(self) -> None:
        """Main autonomy loop."""
        if not self._config.autonomy.enabled:
            return

        self._running = True
        self._bus.subscribe(VisionFrame, self._on_vision_frame)
        self._bus.subscribe(UserInput, self._on_user_input)

        while self._running:
            await self._evaluate()
            await asyncio.sleep(0.1)  # Check frequently, act infrequently

    def stop(self) -> None:
        self._running = False

    async def _on_vision_frame(self, event: VisionFrame) -> None:
        """Track latest vision frame."""
        self._latest_frame = event

    async def _on_user_input(self, event: UserInput) -> None:
        """Track last user interaction time."""
        self._last_input_time = time.time()

    async def _evaluate(self) -> None:
        """Evaluate whether to trigger an autonomous reaction."""
        now = time.time()

        # Respect cooldown
        if now - self._last_trigger_time < self._config.autonomy.cooldown_seconds:
            return

        triggers = self._config.autonomy.triggers

        # Check idle timeout
        if "idle_timeout" in triggers:
            idle_duration = now - self._last_input_time
            if idle_duration >= self._config.autonomy.idle_timeout_seconds:
                await self._trigger("idle_timeout", f"No interaction for {idle_duration:.0f}s")
                return

        # Check screen change
        if "screen_change" in triggers and self._latest_frame:
            frame_hash = hashlib.md5(self._latest_frame.image).hexdigest()
            if self._last_frame_hash and frame_hash != self._last_frame_hash:
                await self._trigger("screen_change", "Screen content changed significantly")
            self._last_frame_hash = frame_hash

    async def _trigger(self, reason: str, context: str) -> None:
        """Emit an autonomous trigger event."""
        self._last_trigger_time = time.time()
        self._last_input_time = time.time()  # Reset idle timer
        logger.info("Autonomous trigger: %s — %s", reason, context)
        await self._bus.publish(AutonomousTrigger(reason=reason, context=context))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_autonomy.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/autonomy/ tests/test_autonomy.py
git commit -m "feat: autonomy loop with idle timeout and screen change triggers"
```

---

### Task 12: Messaging System (Discord)

**Files:**
- Create: `shannon/messaging/__init__.py`
- Create: `shannon/messaging/manager.py`
- Create: `shannon/messaging/providers/__init__.py`
- Create: `shannon/messaging/providers/base.py`
- Create: `shannon/messaging/providers/discord.py`
- Create: `tests/test_messaging.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_messaging.py
from unittest.mock import AsyncMock, MagicMock
from shannon.bus import EventBus
from shannon.messaging.manager import MessagingManager
from shannon.messaging.providers.base import MessagingProvider
from shannon.events import ChatMessage, ChatResponse


def test_messaging_provider_is_abstract():
    try:
        MessagingProvider()  # type: ignore
        assert False
    except TypeError:
        pass


class FakeMessaging(MessagingProvider):
    def __init__(self):
        self.connected = False
        self.sent_messages: list[tuple[str, str]] = []
        self._callback = None

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def send_message(self, channel, text, reply_to=None):
        self.sent_messages.append((channel, text))

    def on_message(self, callback):
        self._callback = callback

    def platform_name(self) -> str:
        return "fake"

    async def simulate_message(self, text, author, channel):
        if self._callback:
            await self._callback(text, author, channel, "msg123")


async def test_messaging_manager_receives_message():
    bus = EventBus()
    provider = FakeMessaging()

    received = []
    async def capture(event: ChatMessage):
        received.append(event)
    bus.subscribe(ChatMessage, capture)

    manager = MessagingManager(bus, [provider])
    await manager.start()

    await provider.simulate_message("hello", "user1", "general")

    assert len(received) == 1
    assert received[0].text == "hello"
    assert received[0].platform == "fake"


async def test_messaging_manager_sends_response():
    bus = EventBus()
    provider = FakeMessaging()

    manager = MessagingManager(bus, [provider])
    await manager.start()

    await bus.publish(ChatResponse(
        text="hi back!",
        platform="fake",
        channel="general",
        reply_to="msg123",
    ))

    assert len(provider.sent_messages) == 1
    assert provider.sent_messages[0] == ("general", "hi back!")


async def test_messaging_manager_routes_to_correct_platform():
    bus = EventBus()
    provider_a = FakeMessaging()
    provider_a.platform_name = lambda: "alpha"
    provider_b = FakeMessaging()
    provider_b.platform_name = lambda: "beta"

    manager = MessagingManager(bus, [provider_a, provider_b])
    await manager.start()

    await bus.publish(ChatResponse(text="for beta", platform="beta", channel="ch1"))

    assert len(provider_a.sent_messages) == 0
    assert len(provider_b.sent_messages) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_messaging.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement messaging providers and manager**

```python
# shannon/messaging/__init__.py
# (empty)

# shannon/messaging/providers/__init__.py
# (empty)

# shannon/messaging/providers/base.py
"""Abstract base for messaging providers."""

from abc import ABC, abstractmethod
from typing import Callable, Coroutine, Any


class MessagingProvider(ABC):
    """Abstract base class for chat platform providers."""

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        ...

    @abstractmethod
    def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Register a callback: async def callback(text, author, channel, message_id)"""
        ...

    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier (e.g. 'discord')."""
        ...
```

```python
# shannon/messaging/providers/discord.py
"""Discord messaging provider using discord.py."""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from shannon.messaging.providers.base import MessagingProvider

logger = logging.getLogger(__name__)


class DiscordProvider(MessagingProvider):
    """Discord bot integration via discord.py."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._client = None
        self._callback = None
        self._task = None

    def platform_name(self) -> str:
        return "discord"

    async def connect(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_message(message):
            # Ignore own messages
            if message.author == self._client.user:
                return
            if self._callback:
                await self._callback(
                    message.content,
                    str(message.author),
                    str(message.channel.id),
                    str(message.id),
                )

        @self._client.event
        async def on_ready():
            logger.info("Discord bot connected as %s", self._client.user)

        self._task = asyncio.create_task(self._client.start(self._token))

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()

    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        if not self._client:
            return
        ch = self._client.get_channel(int(channel))
        if ch is None:
            ch = await self._client.fetch_channel(int(channel))
        if ch:
            if reply_to:
                try:
                    msg = await ch.fetch_message(int(reply_to))
                    await msg.reply(text)
                except Exception:
                    await ch.send(text)
            else:
                await ch.send(text)

    def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        self._callback = callback
```

```python
# shannon/messaging/manager.py
"""Messaging manager — bridges chat platforms to the event bus."""

import logging

from shannon.bus import EventBus
from shannon.events import ChatMessage, ChatResponse
from shannon.messaging.providers.base import MessagingProvider

logger = logging.getLogger(__name__)


class MessagingManager:
    """Bridges messaging providers to the event bus."""

    def __init__(self, bus: EventBus, providers: list[MessagingProvider]) -> None:
        self._bus = bus
        self._providers = {p.platform_name(): p for p in providers}

    async def start(self) -> None:
        """Connect all providers and subscribe to events."""
        self._bus.subscribe(ChatResponse, self._on_chat_response)

        for name, provider in self._providers.items():
            provider.on_message(self._make_handler(name))
            await provider.connect()
            logger.info("Messaging provider '%s' connected", name)

    async def stop(self) -> None:
        """Disconnect all providers."""
        for provider in self._providers.values():
            await provider.disconnect()

    def _make_handler(self, platform: str):
        """Create a message handler for a specific platform."""
        async def handler(text: str, author: str, channel: str, message_id: str):
            await self._bus.publish(ChatMessage(
                text=text,
                author=author,
                platform=platform,
                channel=channel,
                message_id=message_id,
            ))
        return handler

    async def _on_chat_response(self, event: ChatResponse) -> None:
        """Route outgoing responses to the correct platform."""
        provider = self._providers.get(event.platform)
        if provider:
            await provider.send_message(
                event.channel,
                event.text,
                reply_to=event.reply_to or None,
            )
        else:
            logger.warning("No messaging provider for platform: %s", event.platform)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_messaging.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/messaging/ tests/test_messaging.py
git commit -m "feat: messaging system with Discord provider"
```

---

### Task 13: App Entry Point + CLI

**Files:**
- Create: `shannon/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_app.py
import sys
from unittest.mock import patch
from shannon.app import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.config == "config.yaml"
    assert args.dangerously_skip_permissions is False


def test_parse_args_custom_config():
    args = parse_args(["--config", "my_config.yaml"])
    assert args.config == "my_config.yaml"


def test_parse_args_skip_permissions():
    args = parse_args(["--dangerously-skip-permissions"])
    assert args.dangerously_skip_permissions is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement app.py**

```python
# shannon/app.py
"""Shannon AI VTuber — entry point."""

import argparse
import asyncio
import logging
import sys

from shannon.bus import EventBus
from shannon.config import ShannonConfig, load_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shannon — AI VTuber")
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--dangerously-skip-permissions", action="store_true",
        help="Set all action approvals to 'allow' (no confirmation prompts)",
    )
    parser.add_argument(
        "--speech", action="store_true",
        help="Enable speech input/output mode",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


async def run(config: ShannonConfig, speech_mode: bool = False) -> None:
    """Wire up all modules and run Shannon."""
    bus = EventBus()

    # --- LLM Provider ---
    if config.providers.llm.type == "claude":
        from shannon.brain.providers.claude import ClaudeProvider
        llm = ClaudeProvider(
            model=config.providers.llm.model,
            max_tokens=config.providers.llm.max_tokens,
        )
    elif config.providers.llm.type == "ollama":
        from shannon.brain.providers.ollama import OllamaProvider
        llm = OllamaProvider(model=config.providers.llm.model)
    else:
        raise ValueError(f"Unknown LLM provider: {config.providers.llm.type}")

    # --- Memory ---
    from shannon.brain.providers.memory_markdown import MarkdownMemoryProvider
    from shannon.brain.memory import MemoryManager
    memory_provider = MarkdownMemoryProvider(config.memory.dir)
    memory_manager = MemoryManager(memory_provider)

    # --- Brain ---
    from shannon.brain.brain import Brain
    brain = Brain(bus, llm, memory_manager, config)
    await brain.start()

    # --- Input ---
    from shannon.input.providers.text import TextInputProvider
    from shannon.input.manager import InputManager

    text_provider = TextInputProvider()
    stt_provider = None
    if speech_mode:
        try:
            from shannon.input.providers.whisper import WhisperProvider
            stt_provider = WhisperProvider(
                model=config.providers.stt.model,
                device=config.providers.stt.device,
            )
        except ImportError:
            logging.warning("faster-whisper not installed — speech input disabled")

    input_manager = InputManager(bus, text_provider=text_provider, stt_provider=stt_provider)

    # --- Output ---
    from shannon.output.manager import OutputManager

    tts_provider = None
    if speech_mode:
        try:
            from shannon.output.providers.tts.piper import PiperProvider
            tts_provider = PiperProvider(
                model=config.providers.tts.model,
                rate=config.providers.tts.rate,
            )
        except ImportError:
            logging.warning("piper-tts not installed — speech output disabled")

    vtuber_provider = None
    try:
        from shannon.output.providers.vtuber.vtube_studio import VTubeStudioProvider
        vtuber_provider = VTubeStudioProvider(
            host=config.providers.vtuber.host,
            port=config.providers.vtuber.port,
        )
    except ImportError:
        logging.warning("websockets not installed — VTuber integration disabled")

    output_manager = OutputManager(
        bus,
        tts_provider=tts_provider,
        vtuber_provider=vtuber_provider,
        speech_output=speech_mode,
    )
    await output_manager.start()

    # --- Vision ---
    from shannon.vision.manager import VisionManager
    from shannon.vision.providers.base import VisionProvider as VisionProviderBase

    vision_providers: list[VisionProviderBase] = []
    if config.providers.vision.screen:
        try:
            from shannon.vision.providers.screen import ScreenCapture
            vision_providers.append(ScreenCapture())
        except ImportError:
            logging.warning("mss not installed — screen capture disabled")
    if config.providers.vision.webcam:
        try:
            from shannon.vision.providers.webcam import WebcamCapture
            vision_providers.append(WebcamCapture())
        except ImportError:
            logging.warning("opencv not installed — webcam capture disabled")

    vision_manager = VisionManager(
        bus,
        providers=vision_providers,
        interval_seconds=config.providers.vision.interval_seconds,
    )

    # --- Actions ---
    from shannon.actions.manager import ActionManager
    from shannon.actions.providers.shell import ShellAction

    action_providers: dict = {"shell": ShellAction(config.actions.shell)}

    try:
        from shannon.actions.providers.browser import BrowserAction
        action_providers["browser"] = BrowserAction(config.actions.browser)
    except ImportError:
        logging.warning("playwright not installed — browser actions disabled")

    try:
        from shannon.actions.providers.mouse import MouseAction
        from shannon.actions.providers.keyboard import KeyboardAction
        action_providers["mouse"] = MouseAction(config.actions.mouse)
        action_providers["keyboard"] = KeyboardAction(config.actions.keyboard)
    except ImportError:
        logging.warning("pyautogui not installed — mouse/keyboard actions disabled")

    action_manager = ActionManager(bus, action_providers, config)
    await action_manager.start()

    # --- Autonomy ---
    from shannon.autonomy.loop import AutonomyLoop
    autonomy_loop = AutonomyLoop(bus, config)

    # --- Messaging ---
    from shannon.messaging.manager import MessagingManager
    messaging_providers = []
    if config.providers.messaging.enabled and config.providers.messaging.token:
        try:
            from shannon.messaging.providers.discord import DiscordProvider
            messaging_providers.append(DiscordProvider(config.providers.messaging.token))
        except ImportError:
            logging.warning("discord.py not installed — Discord integration disabled")

    messaging_manager = MessagingManager(bus, messaging_providers)
    await messaging_manager.start()

    # --- Run ---
    print(f"Shannon is online! (LLM: {config.providers.llm.type}, Speech: {'on' if speech_mode else 'off'})")
    print("Type a message and press Enter. Ctrl+C to quit.\n")

    tasks = [
        asyncio.create_task(input_manager.run_text_loop()),
    ]
    if vision_providers:
        tasks.append(asyncio.create_task(vision_manager.run()))
    if config.autonomy.enabled:
        tasks.append(asyncio.create_task(autonomy_loop.run()))

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        vision_manager.stop()
        autonomy_loop.stop()
        await output_manager.stop()
        await messaging_manager.stop()
        print("\nShannon is offline. Goodbye!")


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config(args.config)
    if args.dangerously_skip_permissions:
        config.apply_dangerously_skip_permissions()
        logging.warning("Running with --dangerously-skip-permissions: all actions set to allow!")

    try:
        asyncio.run(run(config, speech_mode=args.speech))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_app.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/app.py tests/test_app.py
git commit -m "feat: app entry point with CLI args and module wiring"
```

---

### Task 14: Ollama LLM Provider

**Files:**
- Create: `shannon/brain/providers/ollama.py`

- [ ] **Step 1: Write failing test — add to tests/test_brain.py**

Append to `tests/test_brain.py`:

```python
from shannon.brain.providers.ollama import OllamaProvider


def test_ollama_provider_capabilities():
    provider = OllamaProvider(model="llama3")
    # Ollama doesn't support tools natively for most models
    assert provider.supports_streaming() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_brain.py::test_ollama_provider_capabilities -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement OllamaProvider**

```python
# shannon/brain/providers/ollama.py
"""Ollama LLM provider using REST API."""

import json
import logging
from typing import Any, AsyncIterator

from shannon.brain.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMToolCall,
    LLMToolDef,
)

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """LLM provider using Ollama's local REST API."""

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    def supports_vision(self) -> bool:
        # Models like llava support vision
        vision_models = ["llava", "bakllava", "moondream"]
        return any(vm in self._model.lower() for vm in vision_models)

    def supports_tools(self) -> bool:
        return False  # Most Ollama models don't support tool use reliably

    def supports_streaming(self) -> bool:
        return True

    def _build_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert LLMMessages to Ollama API format."""
        api_messages: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.images:
                import base64
                entry["images"] = [base64.b64encode(img).decode() for img in msg.images]
            api_messages.append(entry)
        return api_messages

    async def generate(self, messages: list[LLMMessage], tools: list[LLMToolDef] | None = None) -> LLMResponse:
        import httpx

        api_messages = self._build_messages(messages)

        # If tools are provided, inject them into the system prompt as instructions
        if tools:
            tool_instructions = self._tools_as_instructions(tools)
            # Prepend to the first system message or add one
            if api_messages and api_messages[0]["role"] == "system":
                api_messages[0]["content"] += f"\n\n{tool_instructions}"
            else:
                api_messages.insert(0, {"role": "system", "content": tool_instructions})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": api_messages,
                    "stream": False,
                    "format": "json" if tools else None,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        text = data.get("message", {}).get("content", "")

        # Try to parse structured output if tools were requested
        tool_calls: list[LLMToolCall] = []
        if tools:
            tool_calls, text = self._parse_tool_calls(text)

        return LLMResponse(text=text, tool_calls=tool_calls)

    async def stream(self, messages: list[LLMMessage], tools: list[LLMToolDef] | None = None) -> AsyncIterator[str]:
        import httpx

        api_messages = self._build_messages(messages)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": api_messages,
                    "stream": True,
                },
                timeout=120.0,
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content

    def _tools_as_instructions(self, tools: list[LLMToolDef]) -> str:
        """Convert tools to text instructions for models without tool_use support."""
        lines = [
            "You have the following tools available. To use a tool, respond with a JSON object "
            'containing "tool_calls": [{"name": "tool_name", "arguments": {...}}] and optionally '
            '"text" for your spoken response.\n\nAvailable tools:'
        ]
        for tool in tools:
            params = json.dumps(tool.parameters.get("properties", {}), indent=2)
            lines.append(f"\n- **{tool.name}**: {tool.description}\n  Parameters: {params}")
        return "\n".join(lines)

    def _parse_tool_calls(self, text: str) -> tuple[list[LLMToolCall], str]:
        """Try to parse tool calls from JSON response text."""
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                calls = []
                for i, tc in enumerate(data.get("tool_calls", [])):
                    calls.append(LLMToolCall(
                        id=f"ollama_{i}",
                        name=tc["name"],
                        arguments=tc.get("arguments", {}),
                    ))
                return calls, data.get("text", "")
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        return [], text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_brain.py::test_ollama_provider_capabilities -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/brain/providers/ollama.py tests/test_brain.py
git commit -m "feat: Ollama LLM provider with REST API"
```

---

### Task 15: Integration Test — Full Pipeline

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
"""Integration test — verifies the full event pipeline with fake providers."""

import asyncio
import tempfile
import shutil

from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import (
    UserInput,
    LLMResponse,
    ActionRequest,
    ActionResult,
    ChatMessage,
    ChatResponse,
    VisionFrame,
    AutonomousTrigger,
)
from shannon.brain.brain import Brain
from shannon.brain.memory import MemoryManager
from shannon.brain.providers.base import LLMProvider, LLMResponse as LLMProviderResponse, LLMMessage, LLMToolDef
from shannon.brain.providers.memory_markdown import MarkdownMemoryProvider
from shannon.input.manager import InputManager
from shannon.input.providers.text import TextInputProvider
from shannon.output.manager import OutputManager
from shannon.actions.manager import ActionManager
from shannon.actions.providers.shell import ShellAction


class FakeLLM(LLMProvider):
    def __init__(self):
        self.call_count = 0

    async def generate(self, messages, tools=None):
        self.call_count += 1
        return LLMProviderResponse(text=f"Response #{self.call_count}")

    async def stream(self, messages, tools=None):
        yield "streamed"


async def test_full_pipeline_text_to_response():
    """User input → Brain → LLM → LLMResponse event."""
    bus = EventBus()
    config = ShannonConfig()
    config.actions.shell.approval = "allow"
    tmpdir = tempfile.mkdtemp()

    llm = FakeLLM()
    memory = MemoryManager(MarkdownMemoryProvider(tmpdir))
    brain = Brain(bus, llm, memory, config)
    await brain.start()

    output = OutputManager(bus, speech_output=False)
    await output.start()

    shell = ShellAction(config.actions.shell)
    actions = ActionManager(bus, {"shell": shell}, config)
    await actions.start()

    responses = []
    async def capture(event: LLMResponse):
        responses.append(event)
    bus.subscribe(LLMResponse, capture)

    # Simulate user input
    await bus.publish(UserInput(text="What's up?", source="text"))

    assert len(responses) == 1
    assert responses[0].text == "Response #1"
    assert llm.call_count == 1

    # Second message
    await bus.publish(UserInput(text="Tell me more", source="text"))
    assert len(responses) == 2
    assert responses[1].text == "Response #2"

    shutil.rmtree(tmpdir)


async def test_chat_message_round_trip():
    """ChatMessage → Brain → ChatResponse."""
    bus = EventBus()
    config = ShannonConfig()
    tmpdir = tempfile.mkdtemp()

    llm = FakeLLM()
    memory = MemoryManager(MarkdownMemoryProvider(tmpdir))
    brain = Brain(bus, llm, memory, config)
    await brain.start()

    chat_responses = []
    async def capture(event: ChatResponse):
        chat_responses.append(event)
    bus.subscribe(ChatResponse, capture)

    await bus.publish(ChatMessage(
        text="hello from discord",
        author="testuser",
        platform="discord",
        channel="123456",
        message_id="msg789",
    ))

    assert len(chat_responses) == 1
    assert chat_responses[0].platform == "discord"
    assert chat_responses[0].channel == "123456"

    shutil.rmtree(tmpdir)
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/test_integration.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/a9lim/Work/shannon && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for full event pipeline"
```
