"""Webhook event models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WebhookEvent:
    source: str
    event_type: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    channel_target: str = ""
