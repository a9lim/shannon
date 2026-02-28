"""Shannon entry point — wires everything together and runs the bot."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

import click

from shannon.config import Settings, load_settings
from shannon.core.auth import AuthManager, PermissionLevel
from shannon.core.bus import Event, EventBus, EventType, MessageOutgoing
from shannon.core.chunker import chunk_message
from shannon.core.context import ContextManager
from shannon.core.llm import AnthropicProvider, LLMMessage, LLMResponse
from shannon.core.scheduler import Scheduler
from shannon.core.system_prompt import build_system_prompt
from shannon.tools.base import BaseTool, ToolResult
from shannon.tools.shell import ShellTool
from shannon.transports.discord_transport import DiscordTransport
from shannon.utils.logging import get_logger, setup_logging

log = get_logger(__name__)


class Shannon:
    """Main application orchestrator."""

    def __init__(self, settings: Settings, dry_run: bool = False) -> None:
        self.settings = settings
        self.dry_run = dry_run

        # Core components
        self.bus = EventBus()
        self.auth = AuthManager(settings.auth)
        self.llm = AnthropicProvider(settings.llm)
        self.context = ContextManager(
            db_path=settings.get_data_dir() / "context.db",
            llm=self.llm,
            max_context_tokens=settings.llm.max_context_tokens,
        )
        self.scheduler = Scheduler(settings.scheduler, self.bus, settings.get_data_dir())

        # Tools
        self.tools: list[BaseTool] = [ShellTool()]
        self._tool_map: dict[str, BaseTool] = {t.name: t for t in self.tools}

        # Transports
        self.transports: list[Any] = []

    async def start(self) -> None:
        log.info("shannon_starting", version="0.1.0")

        # Initialize context DB
        await self.context.start()

        # Subscribe to incoming messages
        self.bus.subscribe(EventType.MESSAGE_INCOMING, self._handle_message)

        # Start scheduler
        if self.settings.scheduler.enabled:
            await self.scheduler.start()

        # Start transports
        if self.settings.discord.token:
            transport = DiscordTransport(
                self.settings.discord, self.bus, self.settings.chunker
            )
            self.transports.append(transport)
            await transport.start()

        # Start bus consumers
        await self.bus.start()

        log.info("shannon_ready")

    async def stop(self) -> None:
        log.info("shannon_stopping")
        await self.bus.stop()
        for transport in self.transports:
            await transport.stop()
        await self.scheduler.stop()
        await self.context.stop()
        log.info("shannon_stopped")

    async def _handle_message(self, event: Event) -> None:
        data = event.data
        platform = data["platform"]
        channel = data["channel"]
        user_id = data["user_id"]
        user_name = data.get("user_name", user_id)
        content = data["content"]

        log.info("message_received", platform=platform, user=user_name, channel=channel)

        # Handle slash commands
        if content.startswith("/"):
            await self._handle_command(platform, channel, user_id, content)
            return

        # Auth check
        level = self.auth.get_level(platform, user_id)
        if level < PermissionLevel.PUBLIC:
            return

        # Store user message in context
        await self.context.add_message(platform, channel, user_id, "user", content)

        if self.dry_run:
            await self._send(platform, channel, f"[DRY RUN] Would process: {content[:100]}")
            return

        # Load conversation context
        messages = await self.context.get_context(platform, channel, user_id)

        # Build system prompt with tools
        system = build_system_prompt(self.tools)

        # Get tool schemas for Anthropic
        tool_schemas = [t.to_anthropic_schema() for t in self.tools]

        # LLM call with tool loop
        response = await self._llm_with_tools(
            messages, system, tool_schemas, platform, user_id, level
        )

        # Store assistant response
        if response:
            await self.context.add_message(platform, channel, user_id, "assistant", response)
            await self._send(platform, channel, response, reply_to=data.get("message_id"))

    async def _llm_with_tools(
        self,
        messages: list[LLMMessage],
        system: str,
        tool_schemas: list[dict[str, Any]],
        platform: str,
        user_id: str,
        user_level: PermissionLevel,
        max_iterations: int = 10,
    ) -> str:
        """Run LLM completion with tool-use loop."""
        current_messages = list(messages)

        for _ in range(max_iterations):
            response: LLMResponse = await self.llm.complete(
                messages=current_messages,
                system=system,
                tools=tool_schemas if self.tools else None,
            )

            # No tool calls — return the text
            if not response.tool_calls:
                return response.content

            # Process tool calls
            tool_results_content: list[dict[str, Any]] = []

            # Add assistant message with tool use
            assistant_content: list[dict[str, Any]] = []
            if response.content:
                assistant_content.append({"type": "text", "text": response.content})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            current_messages.append(LLMMessage(role="assistant", content=assistant_content))

            for tc in response.tool_calls:
                tool = self._tool_map.get(tc.name)
                if not tool:
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: Unknown tool '{tc.name}'",
                        "is_error": True,
                    })
                    continue

                # Permission check
                if user_level < tool.required_permission:
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Permission denied. Tool '{tc.name}' requires level {tool.required_permission}, you have {user_level}.",
                        "is_error": True,
                    })
                    continue

                # Execute tool
                log.info("tool_executing", tool=tc.name, args=tc.arguments)
                result: ToolResult = await tool.execute(**tc.arguments)

                output = result.output if result.success else f"Error: {result.error}"
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": output,
                    "is_error": not result.success,
                })

            current_messages.append(LLMMessage(role="user", content=tool_results_content))

        return response.content if response else ""

    async def _handle_command(
        self, platform: str, channel: str, user_id: str, content: str
    ) -> None:
        """Handle slash commands."""
        parts = content.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/forget":
            count = await self.context.forget(platform, channel)
            await self._send(platform, channel, f"Cleared {count} messages from context.")

        elif command == "/context":
            stats = await self.context.get_stats(platform, channel)
            await self._send(
                platform, channel,
                f"Context: {stats['message_count']} messages, {stats['total_chars']} chars",
            )

        elif command == "/jobs":
            jobs = await self.scheduler.list_jobs()
            if not jobs:
                await self._send(platform, channel, "No scheduled jobs.")
                return
            lines = [f"**{j.name}** — `{j.cron_expr}` — {j.action}" for j in jobs]
            await self._send(platform, channel, "\n".join(lines))

        elif command == "/help":
            await self._send(
                platform, channel,
                "**Commands:** /forget, /context, /jobs, /help",
            )
        else:
            await self._send(platform, channel, f"Unknown command: {command}")

    async def _send(
        self, platform: str, channel: str, content: str, reply_to: str | None = None
    ) -> None:
        """Publish an outgoing message to the bus."""
        await self.bus.publish(
            MessageOutgoing(data={
                "platform": platform,
                "channel": channel,
                "content": content,
                "reply_to": reply_to,
            })
        )


async def run(settings: Settings, dry_run: bool = False) -> None:
    app = Shannon(settings, dry_run=dry_run)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("shutdown_signal")
        stop_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

    await app.start()

    try:
        if sys.platform == "win32":
            # Windows doesn't support loop signal handlers, poll instead
            while not stop_event.is_set():
                await asyncio.sleep(1)
        else:
            await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await app.stop()


@click.command()
@click.option("--config", "config_path", default=None, help="Path to config YAML file")
@click.option("--log-level", default=None, help="Log level (DEBUG, INFO, WARNING, ERROR)")
@click.option("--dry-run", is_flag=True, help="Don't send to LLM, echo messages instead")
def cli(config_path: str | None, log_level: str | None, dry_run: bool) -> None:
    """Start Shannon, the autonomous assistant."""
    settings = load_settings(config_path)
    if log_level:
        settings.log_level = log_level
    setup_logging(level=settings.log_level, json_output=settings.log_json)
    asyncio.run(run(settings, dry_run=dry_run))


if __name__ == "__main__":
    cli()
