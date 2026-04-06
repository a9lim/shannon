# shannon/config.py
"""Configuration loading and validation."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger(__name__)

_SKIP_VALIDATION = False


def _clamp(value: float, lo: float, hi: float, name: str) -> float:
    """Clamp a value to [lo, hi], logging a warning if out of range."""
    if lo <= value <= hi:
        return value
    clamped = max(lo, min(hi, value))
    _log.warning("%s=%.4g out of range [%.4g, %.4g]; clamping to %.4g.", name, value, lo, hi, clamped)
    return clamped


@dataclass
class LLMConfig:
    model: str = "claude-sonnet-4-5-20250514"
    max_tokens: int = 8192
    thinking: bool = True
    compaction: bool = True
    enable_1m_context: bool = True
    api_key: str = ""

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.max_tokens = max(1, self.max_tokens)
        if not self.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError(
                "API key required: set llm.api_key in config.yaml or ANTHROPIC_API_KEY env var"
            )


@dataclass
class TTSConfig:
    type: str = "piper"
    model: str = "en_US-lessac-high"
    rate: float = 1.0
    speaker: str = ""
    noise_scale: float = 1.0
    noise_w_scale: float = 1.0
    sentence_silence: float = 0.25


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

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        if self.interval_seconds < 1.0:
            _log.warning("vision.interval_seconds=%.4g too low; using 1.0", self.interval_seconds)
            self.interval_seconds = 1.0


@dataclass
class VTuberConfig:
    type: str = "vtube_studio"
    host: str = "localhost"
    port: int = 8001
    auth_token: str = ""


@dataclass
class VoiceConfig:
    enabled: bool = False
    auto_join_channels: list[str] = field(default_factory=list)
    silence_threshold: float = 2.0
    buffer_max_seconds: float = 30.0
    voice_reply_probability: float = 1.0
    mute_during_playback: bool = True
    volume: float = 1.0

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.silence_threshold = _clamp(self.silence_threshold, 0.5, 10.0, "silence_threshold")
        self.buffer_max_seconds = _clamp(self.buffer_max_seconds, 5.0, 60.0, "buffer_max_seconds")
        self.voice_reply_probability = _clamp(self.voice_reply_probability, 0, 1, "voice_reply_probability")
        self.volume = _clamp(self.volume, 0, 2, "volume")


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
    voice: VoiceConfig = field(default_factory=VoiceConfig)

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.debounce_delay = _clamp(self.debounce_delay, 0, 60, "debounce_delay")
        self.reply_probability = _clamp(self.reply_probability, 0, 1, "reply_probability")
        self.reaction_probability = _clamp(self.reaction_probability, 0, 1, "reaction_probability")
        self.conversation_expiry = _clamp(self.conversation_expiry, 0, 3600, "conversation_expiry")
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

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.timeout_seconds = max(1, self.timeout_seconds)


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

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.cooldown_seconds = max(0, self.cooldown_seconds)
        self.idle_timeout_seconds = max(1, self.idle_timeout_seconds)


@dataclass
class PersonalityConfig:
    name: str = "Shannon"
    prompt_file: str = "personality.md"


@dataclass
class MemoryConfig:
    dir: str = "memory"
    max_session_messages: int = 40
    recall_top_k: int = 5
    max_continues: int = 5

    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.max_session_messages = max(0, self.max_session_messages)
        self.max_continues = max(0, self.max_continues)


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
    visited_keys: set[str] = set()
    for key, value in overrides.items():
        if not hasattr(instance, key):
            _log.warning("Unknown config key %r — ignored (typo?)", key)
            continue
        visited_keys.add(key)
        current = getattr(instance, key)
        if isinstance(value, dict) and hasattr(current, "__dataclass_fields__"):
            _merge_dataclass(current, value)
        else:
            # Type coercion: bool before int (bool is subclass of int)
            if isinstance(current, list) and not isinstance(value, list):
                value = [value] if value is not None else []
            elif isinstance(current, bool) and not isinstance(value, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(value, (int, bool)):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    _log.warning("Cannot convert %r to int for %s; skipping", value, key)
                    continue
            elif isinstance(current, float) and not isinstance(value, (float, int)):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    _log.warning("Cannot convert %r to float for %s; skipping", value, key)
                    continue
            setattr(instance, key, value)
    # Recurse into nested dataclass fields that were NOT in overrides,
    # so their __post_init__ validators still run.
    if hasattr(instance, "__dataclass_fields__"):
        for field_name in instance.__dataclass_fields__:
            if field_name not in visited_keys:
                child = getattr(instance, field_name)
                if hasattr(child, "__dataclass_fields__"):
                    _merge_dataclass(child, {})
    # Re-run validation after merging overrides
    if hasattr(instance, "__post_init__"):
        instance.__post_init__()


def _build_defaults() -> ShannonConfig:
    """Build ShannonConfig with defaults, skipping __post_init__ validation."""
    global _SKIP_VALIDATION
    _SKIP_VALIDATION = True
    try:
        config = ShannonConfig()
    finally:
        _SKIP_VALIDATION = False
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
