"""Typed message models replacing untyped event data dicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncomingMessage:
    platform: str
    channel: str
    user_id: str
    content: str
    user_name: str = ""
    message_id: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    group_id: str = ""
    guild_id: str | None = None


@dataclass
class OutgoingMessage:
    platform: str
    channel: str
    content: str
    reply_to: str | None = None
    embed: dict[str, Any] | None = None
    files: list[str] | None = None
