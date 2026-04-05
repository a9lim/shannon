"""Discord messaging provider using discord.py."""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from shannon.messaging.providers.base import MessagingProvider

logger = logging.getLogger(__name__)

DISCORD_MAX_LENGTH = 2000
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB


def split_message(text: str) -> list[str]:
    """Split text into chunks that fit within Discord's 2000-char limit.

    Splitting priority: newlines -> sentence boundaries -> spaces -> hard cut.
    """
    if not text or not text.strip():
        return []
    if len(text) <= DISCORD_MAX_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= DISCORD_MAX_LENGTH:
            chunk = remaining.strip()
            if chunk:
                chunks.append(chunk)
            break

        # Try to split on newline
        cut = remaining.rfind("\n", 0, DISCORD_MAX_LENGTH)
        if cut != -1:
            chunk = remaining[:cut].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut:].lstrip("\n")
            continue

        # Try to split on sentence boundary
        best_sentence = -1
        for punc in (". ", "! ", "? "):
            idx = remaining.rfind(punc, 0, DISCORD_MAX_LENGTH)
            if idx > best_sentence:
                best_sentence = idx + 1  # include the punctuation mark

        if best_sentence > 0:
            chunk = remaining[:best_sentence].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[best_sentence:].lstrip()
            continue

        # Try to split on space
        cut = remaining.rfind(" ", 0, DISCORD_MAX_LENGTH)
        if cut != -1:
            chunk = remaining[:cut + 1]
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut + 1:]
            continue

        # Hard cut
        chunks.append(remaining[:DISCORD_MAX_LENGTH])
        remaining = remaining[DISCORD_MAX_LENGTH:]

    return chunks


class DiscordProvider(MessagingProvider):
    """Messaging provider that connects to Discord via discord.py.

    Requires the ``discord.py`` package (``pip install discord.py``).
    The bot token must have the ``message_content`` privileged intent enabled
    in the Discord Developer Portal.
    """

    def __init__(self, token: str, conversation_expiry: float = 300.0) -> None:
        self._token = token
        self._conversation_expiry = conversation_expiry
        self._callback: Callable[..., Coroutine[Any, Any, None]] | None = None
        self._client: Any = None  # discord.Client, typed as Any to avoid hard import at module level
        self._client_task: Any = None

    # ------------------------------------------------------------------
    # MessagingProvider interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create a discord.Client and start it in the background."""
        import asyncio
        import discord  # type: ignore[import]

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore messages from any bot.
            if message.author.bot:
                return
            if self._callback is not None:
                # Download attachments
                attachments: list[dict] = []
                for att in message.attachments:
                    if att.size > _MAX_ATTACHMENT_BYTES:
                        logger.warning(
                            "Skipping attachment %s — too large (%d bytes)", att.filename, att.size
                        )
                        continue
                    try:
                        data = await att.read()
                        attachments.append({
                            "filename": att.filename,
                            "content_type": att.content_type or "",
                            "data": data,
                        })
                    except Exception:
                        logger.debug("Failed to download attachment %s", att.filename)

                # Detect reply-to-bot
                is_reply_to_bot = False
                if message.reference and message.reference.resolved:
                    ref = message.reference.resolved
                    if isinstance(ref, discord.Message) and ref.author == self._client.user:
                        is_reply_to_bot = True

                # Detect mention
                is_mention = (
                    self._client.user is not None
                    and self._client.user.mentioned_in(message)
                )

                custom_emojis = ""
                if message.guild:
                    custom_emojis = self._get_guild_emojis(message.guild)

                participants = {
                    str(message.author.id): str(message.author.display_name),
                }

                # Only check Discord history when cheaper checks (mention, reply) didn't trigger
                is_in_conversation = False
                if not is_reply_to_bot and not is_mention:
                    is_in_conversation = await self._is_in_conversation(
                        message.channel, self._conversation_expiry
                    )

                is_dm = message.guild is None

                await self._callback(
                    message.content,
                    str(message.author),
                    str(message.channel.id),
                    str(message.id),
                    attachments,
                    is_reply_to_bot,
                    is_mention,
                    custom_emojis,
                    participants,
                    is_in_conversation,
                    is_dm,
                )

        # Start the client in the background without blocking.
        self._client_task = asyncio.ensure_future(self._client.start(self._token))
        self._client_task.add_done_callback(self._on_client_done)

    async def disconnect(self) -> None:
        """Close the Discord client connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _on_client_done(self, task: "asyncio.Task[None]") -> None:
        """Log if the Discord client task exits unexpectedly."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Discord client exited with error: %s", exc)

    async def send_message(self, channel: str, text: str, reply_to: str | None = None) -> None:
        """Fetch the channel by ID and send a message, optionally as a reply.

        Long messages are split at 2000-char boundaries.
        """
        if self._client is None or not text:
            return

        discord_channel = self._client.get_channel(int(channel))
        if discord_channel is None:
            discord_channel = await self._client.fetch_channel(int(channel))

        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            if i == 0 and reply_to:
                try:
                    original = await discord_channel.fetch_message(int(reply_to))
                    await original.reply(chunk)
                except Exception:
                    logger.exception("Failed to reply to message %s", reply_to)
                    await discord_channel.send(chunk)
            else:
                await discord_channel.send(chunk)

    async def send_typing(self, channel: str) -> None:
        """Send a typing indicator to the Discord channel."""
        if self._client is None:
            return
        discord_channel = self._client.get_channel(int(channel))
        if discord_channel is None:
            try:
                discord_channel = await self._client.fetch_channel(int(channel))
            except Exception:
                return
        try:
            await discord_channel.trigger_typing()
        except Exception:
            pass

    async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None:
        """Add an emoji reaction to a Discord message. Failures are silently ignored."""
        if self._client is None:
            return
        try:
            discord_channel = self._client.get_channel(int(channel))
            if discord_channel is None:
                discord_channel = await self._client.fetch_channel(int(channel))
            message = await discord_channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
        except Exception:
            pass

    _MAX_EMOJIS = 50

    def _get_guild_emojis(self, guild) -> str:
        """Build a string listing available custom emoji for context."""
        if not guild or not guild.emojis:
            return ""
        names = [f":{e.name}:" for e in guild.emojis if e.available]
        if not names:
            return ""
        names = names[:self._MAX_EMOJIS]
        return f"Custom emojis: {', '.join(names)}"

    async def _is_in_conversation(self, channel, expiry: float) -> bool:
        """Check if the bot recently replied in this channel by inspecting Discord history."""
        try:
            async for msg in channel.history(limit=7):
                if msg.author == self._client.user:
                    from discord.utils import utcnow
                    age = (utcnow() - msg.created_at).total_seconds()
                    if age < expiry:
                        return True
                    break
        except Exception:
            pass
        return False

    def on_message(self, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """Register callback for incoming messages."""
        self._callback = callback

    def platform_name(self) -> str:
        return "discord"
