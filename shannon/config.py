# shannon/config.py
"""Configuration loading and validation."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)


def _clamp(value: float, lo: float, hi: float, name: str, default: float) -> float:
    """Clamp a value to [lo, hi], logging a warning and returning default if out of range."""
    if lo <= value <= hi:
        return value
    _log.warning("%s=%.4g out of range [%.4g, %.4g]; using %.4g.", name, value, lo, hi, default)
    return default


@dataclass
class LLMConfig:
    model: str = "claude-opus-4-6"
    max_tokens: int = 8192
    thinking: bool = True
    thinking_budget: int = 4096
    compaction: bool = True
    api_key: str = ""

    def __post_init__(self) -> None:
        self.max_tokens = max(1, self.max_tokens)
        if not self.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError(
                "API key required: set llm.api_key in config.yaml or ANTHROPIC_API_KEY env var"
            )


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
    interval_seconds: float = 60.0
    max_width: int = 1024
    max_height: int = 768


@dataclass
class VTuberConfig:
    type: str = "vtube_studio"
    host: str = "localhost"
    port: int = 8001
    auth_token: str = ""


@dataclass
class MessagingConfig:
    type: str = "discord"
    enabled: bool = False
    token: str = ""
    debounce_delay: float = 3.0
    reply_probability: float = 0.0
    reaction_probability: float = 0.0
    conversation_expiry: float = 300.0
    max_context_messages: int = 20
    admin_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.debounce_delay = _clamp(self.debounce_delay, 0, 60, "debounce_delay", 3.0)
        self.reply_probability = _clamp(self.reply_probability, 0, 1, "reply_probability", 0.0)
        self.reaction_probability = _clamp(self.reaction_probability, 0, 1, "reaction_probability", 0.0)
        self.conversation_expiry = _clamp(self.conversation_expiry, 0, 3600, "conversation_expiry", 300.0)
        self.max_context_messages = max(0, self.max_context_messages)
        if self.enabled and not self.token:
            raise ValueError(
                "Discord token required when messaging is enabled: "
                "set messaging.token in config.yaml"
            )


@dataclass
class ComputerUseConfig:
    enabled: bool = True
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
    require_confirmation: bool = True


@dataclass
class ToolsConfig:
    computer_use: ComputerUseConfig = field(default_factory=ComputerUseConfig)
    bash: BashConfig = field(default_factory=BashConfig)
    text_editor: TextEditorConfig = field(default_factory=TextEditorConfig)


@dataclass
class AutonomyConfig:
    enabled: bool = True
    cooldown_seconds: int = 120
    triggers: list[str] = field(default_factory=lambda: ["screen_change", "idle_timeout"])
    idle_timeout_seconds: int = 600


@dataclass
class PersonalityConfig:
    name: str = "Shannon"
    prompt_file: str = "personality.md"


@dataclass
class MemoryConfig:
    dir: str = "memory"
    conversation_window: int = 20
    recall_top_k: int = 5
    max_continues: int = 5


@dataclass
class ShannonConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    vtuber: VTuberConfig = field(default_factory=VTuberConfig)
    messaging: MessagingConfig = field(default_factory=MessagingConfig)
    autonomy: AutonomyConfig = field(default_factory=AutonomyConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    def apply_dangerously_skip_permissions(self) -> None:
        """Set require_confirmation=False on all tools."""
        self.tools.computer_use.require_confirmation = False
        self.tools.bash.require_confirmation = False
        self.tools.text_editor.require_confirmation = False


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
    # Re-run validation after merging overrides
    if hasattr(instance, "__post_init__"):
        instance.__post_init__()


def _build_defaults() -> ShannonConfig:
    """Build ShannonConfig with defaults, skipping __post_init__ validation."""
    llm = LLMConfig.__new__(LLMConfig)
    llm.model = "claude-opus-4-6"
    llm.max_tokens = 8192
    llm.thinking = True
    llm.thinking_budget = 4096
    llm.compaction = True
    llm.api_key = ""

    config = ShannonConfig.__new__(ShannonConfig)
    config.llm = llm
    config.tools = ToolsConfig()
    config.tts = TTSConfig()
    config.stt = STTConfig()
    config.vision = VisionConfig()
    config.vtuber = VTuberConfig()
    config.messaging = MessagingConfig.__new__(MessagingConfig)
    config.messaging.type = "discord"
    config.messaging.enabled = False
    config.messaging.token = ""
    config.messaging.debounce_delay = 3.0
    config.messaging.reply_probability = 0.0
    config.messaging.reaction_probability = 0.0
    config.messaging.conversation_expiry = 300.0
    config.messaging.max_context_messages = 20
    config.messaging.admin_ids = []
    config.autonomy = AutonomyConfig()
    config.personality = PersonalityConfig()
    config.memory = MemoryConfig()
    return config


def load_config(path: str | Path) -> ShannonConfig:
    """Load config from a YAML file, merging over defaults."""
    config = _build_defaults()
    path = Path(path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _merge_dataclass(config, data)
    else:
        # No config file — still need to validate defaults
        _merge_dataclass(config, {})
    return config
