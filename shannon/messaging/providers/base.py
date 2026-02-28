"""Abstract base class for messaging providers."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine


class MessagingProvider(ABC):
    """Abstract interface for external chat platform integrations."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the messaging platform."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the messaging platform."""

    @abstractmethod
    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        """Send a message to a channel, optionally as a reply."""

    @abstractmethod
    async def send_typing(self, channel: str) -> None:
        """Show a typing indicator in the channel."""

    @abstractmethod
    async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None:
        """Add an emoji reaction to a message. Best-effort — failures should be silent."""

    @abstractmethod
    def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Register a callback for incoming messages.

        The callback signature is:
            callback(text, author, channel_id, message_id, attachments, is_reply_to_bot, is_mention, custom_emojis, participants, is_in_conversation)

        Where attachments is a list of dicts with keys: filename, content_type, data (bytes).
        custom_emojis is an optional string listing available custom emoji for the system prompt.
        participants is a dict mapping user IDs to display names.
        is_in_conversation is a bool indicating the bot recently replied in this channel.
        """

    @abstractmethod
    def platform_name(self) -> str:
        """Return the unique platform identifier (e.g. 'discord')."""
