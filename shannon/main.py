"""Shannon entry point — wires everything together and runs the bot."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

import click

from shannon.config import Settings, load_settings
from shannon.core.auth import AuthManager
from shannon.core.bus import EventBus, EventType
from shannon.core.commands import CommandHandler
from shannon.core.context import ContextManager
from shannon.core.llm import create_provider
from shannon.core.pipeline import MessageHandler
from shannon.core.scheduler import Scheduler
from shannon.core.tool_executor import ToolExecutor
from shannon.tools.base import BaseTool
from shannon.tools.shell import ShellTool
from shannon.tools.browser import BrowserTool
from shannon.tools.claude_code import ClaudeCodeTool
from shannon.tools.interactive import InteractiveTool
from shannon.transports.discord_transport import DiscordTransport
from shannon.transports.signal_transport import SignalTransport
from shannon.utils.logging import get_logger, setup_logging

log = get_logger(__name__)


class Shannon:
    """Main application orchestrator — wiring and lifecycle only."""

    def __init__(self, settings: Settings, dry_run: bool = False) -> None:
        self.settings = settings
        self.bus = EventBus()
        self.auth = AuthManager(settings.auth)
        self.llm = create_provider(settings.llm)
        self.context = ContextManager(
            db_path=settings.get_data_dir() / "context.db",
            llm=self.llm,
            max_context_tokens=settings.llm.max_context_tokens,
        )
        self.scheduler = Scheduler(settings.scheduler, self.bus, settings.get_data_dir())

        # Tools
        self.tools: list[BaseTool] = [
            ShellTool(),
            BrowserTool(settings.browser),
            ClaudeCodeTool(),
            InteractiveTool(settings.interactive),
        ]
        tool_map: dict[str, BaseTool] = {t.name: t for t in self.tools}

        # Build pipeline
        tool_executor = ToolExecutor(self.llm, tool_map)
        command_handler = CommandHandler(
            self.context, self.scheduler, self.auth, self._send,
        )
        self._pipeline = MessageHandler(
            self.auth, self.context, tool_executor, command_handler,
            self.bus, self.tools, dry_run=dry_run,
        )

        self.transports: list[Any] = []

    async def start(self) -> None:
        log.info("shannon_starting", version="0.1.0", provider=self.settings.llm.provider)
        await self.context.start()
        self.bus.subscribe(EventType.MESSAGE_INCOMING, self._pipeline.handle)

        if self.settings.scheduler.enabled:
            await self.scheduler.start()

        if self.settings.discord.token:
            t = DiscordTransport(self.settings.discord, self.bus, self.settings.chunker)
            self.transports.append(t)
            await t.start()

        if self.settings.signal.phone_number:
            t = SignalTransport(self.settings.signal, self.bus, self.settings.chunker)
            self.transports.append(t)
            await t.start()

        await self.bus.start()
        log.info("shannon_ready")

    async def stop(self) -> None:
        log.info("shannon_stopping")
        await self.bus.stop()
        for transport in self.transports:
            await transport.stop()
        await self.scheduler.stop()
        await self.context.stop()
        await self.llm.close()
        for tool in self.tools:
            try:
                await tool.cleanup()
            except Exception:
                log.exception("tool_cleanup_error", tool=tool.name)
        log.info("shannon_stopped")

    async def _send(
        self, platform: str, channel: str, content: str
    ) -> None:
        """Send helper used by CommandHandler."""
        from shannon.core.bus import MessageOutgoing
        from shannon.models import OutgoingMessage
        await self.bus.publish(
            MessageOutgoing(message=OutgoingMessage(
                platform=platform, channel=channel, content=content,
            ))
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
