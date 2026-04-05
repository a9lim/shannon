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
    context: str


@dataclass
class LLMResponse:
    """Structured response from the LLM."""
    text: str
    expressions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    mood: str


@dataclass
class SpeechStart:
    """TTS started playing audio."""
    duration: float
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
    platform: str
    channel: str
    message_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    is_reply_to_bot: bool = False
    is_mention: bool = False
    custom_emojis: str = ""
    participants: dict[str, str] = field(default_factory=dict)
    is_dm: bool = False


@dataclass
class ChatResponse:
    """Outgoing response to an external chat platform."""
    text: str
    platform: str
    channel: str
    reply_to: str = ""
    reactions: list[str] = field(default_factory=list)


@dataclass
class ChatReaction:
    """Request to add an emoji reaction to a message."""
    emoji: str
    platform: str
    channel: str
    message_id: str


@dataclass
class ToolConfirmationRequest:
    """Request user approval before executing a tool."""
    tool_name: str
    description: str
    request_id: str


@dataclass
class ToolConfirmationResponse:
    """User's approval/denial of a tool execution."""
    request_id: str
    approved: bool
