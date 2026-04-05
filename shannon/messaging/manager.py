"""MessagingManager — bridges external chat platforms to the event bus."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from shannon.config import MessagingConfig
from shannon.events import ChatMessage, ChatReaction, ChatResponse

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.messaging.providers.base import MessagingProvider

logger = logging.getLogger(__name__)


class MessagingManager:
    """Connects messaging providers to the event bus.

    Incoming messages from any provider are evaluated for response eligibility
    (mentions, replies, active conversations, random chance) and debounced
    before being published as ``ChatMessage`` events.

    ``ChatResponse`` events on the bus are routed back to the correct provider,
    with reactions applied.
    """

    def __init__(
        self,
        bus: "EventBus",
        providers: list["MessagingProvider"],
        config: MessagingConfig | None = None,
    ) -> None:
        self._bus = bus
        self._providers: dict[str, "MessagingProvider"] = {
            p.platform_name(): p for p in providers
        }
        self._config = config or MessagingConfig()
        self._pending: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect all providers, register handlers, and subscribe to the bus."""
        for provider in self._providers.values():
            def _make_handler(p: "MessagingProvider"):
                async def _on_message(
                    text: str,
                    author: str,
                    channel_id: str,
                    message_id: str,
                    attachments: list[dict] | None = None,
                    is_reply_to_bot: bool = False,
                    is_mention: bool = False,
                    custom_emojis: str = "",
                    participants: dict[str, str] | None = None,
                    is_in_conversation: bool = False,
                ) -> None:
                    await self._handle_incoming(
                        platform=p.platform_name(),
                        text=text,
                        author=author,
                        channel_id=channel_id,
                        message_id=message_id,
                        attachments=attachments or [],
                        is_reply_to_bot=is_reply_to_bot,
                        is_mention=is_mention,
                        custom_emojis=custom_emojis,
                        participants=participants or {},
                        is_in_conversation=is_in_conversation,
                    )
                return _on_message

            provider.on_message(_make_handler(provider))
            await provider.connect()

        self._bus.subscribe(ChatResponse, self._on_chat_response)

    async def stop(self) -> None:
        """Disconnect all providers, cancel pending tasks, and unsubscribe."""
        self._bus.unsubscribe(ChatResponse, self._on_chat_response)
        for task in self._pending.values():
            task.cancel()
        self._pending.clear()
        for provider in self._providers.values():
            await provider.disconnect()

    # ------------------------------------------------------------------
    # Incoming message handling
    # ------------------------------------------------------------------

    def _should_respond(
        self,
        platform: str,
        channel_id: str,
        is_reply_to_bot: bool,
        is_mention: bool,
        is_in_conversation: bool = False,
    ) -> bool:
        """Decide whether the bot should respond to this message."""
        if is_mention or is_reply_to_bot:
            return True

        if is_in_conversation:
            return True

        # Random reply chance
        if self._config.reply_probability > 0 and random.random() < self._config.reply_probability:
            return True

        return False

    async def _handle_incoming(
        self,
        platform: str,
        text: str,
        author: str,
        channel_id: str,
        message_id: str,
        attachments: list[dict],
        is_reply_to_bot: bool,
        is_mention: bool,
        custom_emojis: str = "",
        participants: dict[str, str] | None = None,
        is_in_conversation: bool = False,
    ) -> None:
        """Evaluate response eligibility and debounce before publishing."""
        if not self._should_respond(platform, channel_id, is_reply_to_bot, is_mention, is_in_conversation):
            # Maybe react even if not responding
            if self._config.reaction_probability > 0 and random.random() < self._config.reaction_probability:
                await self._bus.publish(
                    ChatReaction(emoji="", platform=platform, channel=channel_id, message_id=message_id)
                )
            return

        key = f"{platform}:{channel_id}"

        # Cancel existing debounce task for this channel
        existing = self._pending.get(key)
        if existing and not existing.done():
            existing.cancel()

        event = ChatMessage(
            text=text,
            author=author,
            platform=platform,
            channel=channel_id,
            message_id=message_id,
            attachments=attachments,
            is_reply_to_bot=is_reply_to_bot,
            is_mention=is_mention,
            custom_emojis=custom_emojis,
            participants=participants or {},
        )

        async def _typing_loop(provider: "MessagingProvider", ch_id: str) -> None:
            """Send typing indicators every 5s until cancelled."""
            try:
                while True:
                    try:
                        await provider.send_typing(ch_id)
                    except Exception:
                        pass
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass

        async def _debounced_publish() -> None:
            typing_task: asyncio.Task | None = None
            try:
                provider = self._providers.get(platform)
                if self._config.debounce_delay > 0:
                    # Show typing during debounce
                    if provider:
                        try:
                            await provider.send_typing(channel_id)
                        except Exception:
                            pass
                    await asyncio.sleep(self._config.debounce_delay)

                # Keep typing indicator alive during LLM generation
                if provider:
                    typing_task = asyncio.create_task(_typing_loop(provider, channel_id))

                await self._bus.publish(event)
            except asyncio.CancelledError:
                pass
            finally:
                if typing_task is not None:
                    typing_task.cancel()
                # Only remove if we're still the current pending task; a newer
                # message may have already replaced our entry in _pending.
                if self._pending.get(key) is task:
                    del self._pending[key]

        task = asyncio.create_task(_debounced_publish())
        self._pending[key] = task

    # ------------------------------------------------------------------
    # Outgoing response handling
    # ------------------------------------------------------------------

    async def _on_chat_response(self, event: ChatResponse) -> None:
        """Route a ChatResponse to the appropriate provider."""
        provider = self._providers.get(event.platform)
        if provider is None:
            return

        # Send typing indicator while preparing response
        try:
            await provider.send_typing(event.channel)
        except Exception:
            pass

        # Send message
        reply_to = event.reply_to if event.reply_to else None
        await provider.send_message(event.channel, event.text, reply_to=reply_to)

        # Apply reactions
        if event.reactions:
            if event.reply_to:
                for emoji in event.reactions:
                    await provider.add_reaction(event.channel, event.reply_to, emoji)
            else:
                logger.debug("Reactions dropped — no reply_to message ID to attach them to")
