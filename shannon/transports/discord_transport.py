"""Discord transport using discord.py."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from shannon.config import ChunkerConfig, DiscordConfig
from shannon.core.bus import EventBus, EventType, Event, MessageIncoming, MessageOutgoing
from shannon.core.chunker import chunk_message
from shannon.models import IncomingMessage, OutgoingMessage
from shannon.transports.base import Transport
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class DiscordTransport(Transport):
    def __init__(
        self,
        config: DiscordConfig,
        bus: EventBus,
        chunker_config: ChunkerConfig | None = None,
    ) -> None:
        super().__init__(bus)
        self._config = config
        self._chunker_config = chunker_config or ChunkerConfig()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        self._client = discord.Client(intents=intents)
        self._setup_handlers()

    @property
    def platform_name(self) -> str:
        return "discord"

    def _setup_handlers(self) -> None:
        @self._client.event
        async def on_ready() -> None:
            log.info("discord_connected", user=str(self._client.user))

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore own messages
            if message.author == self._client.user:
                return

            # Guild filtering
            if self._config.guild_ids and message.guild:
                if message.guild.id not in self._config.guild_ids:
                    return

            # Check if bot is mentioned or in DM
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = self._client.user in message.mentions if self._client.user else False

            if not is_dm and not is_mentioned:
                return

            # Strip bot mention from content
            content = message.content
            if self._client.user:
                content = content.replace(f"<@{self._client.user.id}>", "").strip()
                content = content.replace(f"<@!{self._client.user.id}>", "").strip()

            # Build attachments list
            attachments = [
                {"url": a.url, "filename": a.filename, "size": a.size}
                for a in message.attachments
            ]

            msg = IncomingMessage(
                platform="discord",
                channel=str(message.channel.id),
                user_id=str(message.author.id),
                user_name=message.author.display_name,
                content=content,
                attachments=attachments,
                message_id=str(message.id),
                guild_id=str(message.guild.id) if message.guild else None,
            )

            await self.bus.publish(MessageIncoming(message=msg))

    async def start(self) -> None:
        self.bus.subscribe(EventType.MESSAGE_OUTGOING, self._handle_outgoing)
        asyncio.create_task(
            self._client.start(self._config.token),
            name="discord-client",
        )
        log.info("discord_transport_starting")

    async def stop(self) -> None:
        await self._client.close()
        log.info("discord_transport_stopped")

    async def _handle_outgoing(self, event: Event) -> None:
        msg: OutgoingMessage | None = event.message  # type: ignore[attr-defined]
        if msg is None or msg.platform != "discord":
            return

        channel_id = int(msg.channel)
        content = msg.content
        reply_to = msg.reply_to
        embed_data = msg.embed
        files = msg.files or []

        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                log.error("discord_channel_not_found", channel_id=channel_id)
                return

        if not isinstance(channel, (discord.TextChannel, discord.DMChannel, discord.Thread)):
            log.error("discord_invalid_channel_type", channel_id=channel_id)
            return

        await self.send_message(
            str(channel_id),
            content,
            reply_to=reply_to,
            embed=embed_data,
            files=files,
        )

    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        reply_to: str | None = None,
        embed: dict[str, Any] | None = None,
        files: list[str] | None = None,
    ) -> None:
        channel_id = int(channel)
        discord_channel = self._client.get_channel(channel_id)
        if discord_channel is None:
            discord_channel = await self._client.fetch_channel(channel_id)

        if not isinstance(discord_channel, (discord.TextChannel, discord.DMChannel, discord.Thread)):
            return

        # Build embed if provided
        discord_embed = None
        if embed:
            discord_embed = discord.Embed(
                title=embed.get("title", ""),
                description=embed.get("description", ""),
                color=embed.get("color", 0x5865F2),
            )
            for f in embed.get("fields", []):
                discord_embed.add_field(
                    name=f["name"], value=f["value"], inline=f.get("inline", False)
                )

        # Build file attachments
        discord_files = []
        if files:
            for file_path in files:
                try:
                    discord_files.append(discord.File(file_path))
                except FileNotFoundError:
                    log.warning("discord_file_not_found", path=file_path)

        # Chunk the message
        chunks = chunk_message(
            content,
            limit=self._chunker_config.discord_limit,
            config=self._chunker_config,
        )

        # Determine if we should use a thread for long responses
        use_thread = (
            len(chunks) > 5
            and isinstance(discord_channel, discord.TextChannel)
        )

        target: discord.TextChannel | discord.DMChannel | discord.Thread = discord_channel

        if use_thread and isinstance(discord_channel, discord.TextChannel):
            # Create thread for long responses
            preview = content[:50] + "..." if len(content) > 50 else content
            thread = await discord_channel.create_thread(
                name=f"Response: {preview}",
                type=discord.ChannelType.public_thread,
            )
            target = thread

        # Get reference for reply
        reference = None
        if reply_to and isinstance(discord_channel, discord.TextChannel):
            try:
                ref_msg = await discord_channel.fetch_message(int(reply_to))
                reference = ref_msg.to_reference()
            except (discord.NotFound, ValueError):
                pass

        # Send chunks with typing indicator
        for i, chunk_text in enumerate(chunks):
            kwargs: dict[str, Any] = {"content": chunk_text}

            # Attach embed and files to last chunk
            if i == len(chunks) - 1:
                if discord_embed:
                    kwargs["embed"] = discord_embed
                if discord_files:
                    kwargs["files"] = discord_files

            # Reply reference on first chunk only
            if i == 0 and reference:
                kwargs["reference"] = reference

            async with target.typing():
                await asyncio.sleep(self._chunker_config.typing_delay)
            await target.send(**kwargs)
