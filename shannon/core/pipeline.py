"""Message handling pipeline: rate limit → command → auth → context → LLM → response."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import AuthManager, PermissionLevel
from shannon.core.bus import Event, EventBus, MessageOutgoing
from shannon.core.commands import CommandHandler
from shannon.core.context import ContextManager
from shannon.core.system_prompt import build_system_prompt
from shannon.core.tool_executor import ToolExecutor
from shannon.models import IncomingMessage, OutgoingMessage
from shannon.tools.base import BaseTool
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class MessageHandler:
    """Orchestrates the full message handling pipeline."""

    def __init__(
        self,
        auth: AuthManager,
        context: ContextManager,
        tool_executor: ToolExecutor,
        command_handler: CommandHandler,
        bus: EventBus,
        tools: list[BaseTool],
        dry_run: bool = False,
    ) -> None:
        self._auth = auth
        self._context = context
        self._tool_executor = tool_executor
        self._commands = command_handler
        self._bus = bus
        self._tools = tools
        self._dry_run = dry_run

    async def handle(self, event: Event) -> None:
        msg: IncomingMessage = event.message  # type: ignore[attr-defined]
        platform = msg.platform
        channel = msg.channel
        user_id = msg.user_id
        user_name = msg.user_name or user_id
        content = msg.content

        log.info("message_received", platform=platform, user=user_name, channel=channel)

        # Rate limit check
        if not self._auth.check_rate_limit(platform, user_id):
            await self._send(platform, channel, "You're sending messages too quickly. Please slow down.")
            return

        # Handle slash commands
        if content.startswith("/"):
            await self._commands.handle(platform, channel, user_id, content)
            return

        # Auth check
        level = self._auth.get_level(platform, user_id)
        if level < PermissionLevel.PUBLIC:
            return

        # Store user message in context
        await self._context.add_message(platform, channel, user_id, "user", content)

        if self._dry_run:
            await self._send(platform, channel, f"[DRY RUN] Would process: {content[:100]}")
            return

        # Load conversation context
        messages = await self._context.get_context(platform, channel)

        # Build system prompt with tools filtered by user permission
        available_tools = [t for t in self._tools if level >= t.required_permission]
        system = build_system_prompt(available_tools)
        tool_schemas = [t.to_anthropic_schema() for t in available_tools]

        # LLM call with tool loop
        response = await self._tool_executor.run(
            messages, system, tool_schemas, level
        )

        # Store assistant response
        if response:
            await self._context.add_message(platform, channel, user_id, "assistant", response)
            await self._send(platform, channel, response, reply_to=msg.message_id or None)

    async def _send(
        self, platform: str, channel: str, content: str, reply_to: str | None = None
    ) -> None:
        await self._bus.publish(
            MessageOutgoing(message=OutgoingMessage(
                platform=platform,
                channel=channel,
                content=content,
                reply_to=reply_to,
            ))
        )
