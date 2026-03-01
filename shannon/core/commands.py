"""Slash command handler."""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from shannon.core.auth import AuthManager, PermissionLevel
from shannon.core.context import ContextManager
from shannon.core.pause import PauseManager, parse_duration
from shannon.core.scheduler import Scheduler
from shannon.utils.logging import get_logger

log = get_logger(__name__)

SendFn = Callable[[str, str, str], Coroutine[Any, Any, None]]


class CommandHandler:
    """Dispatches slash commands (/forget, /context, /summarize, /jobs, /sudo, /help)."""

    def __init__(
        self,
        context: ContextManager,
        scheduler: Scheduler,
        auth: AuthManager,
        send_fn: SendFn,
        memory_store: "MemoryStore | None" = None,
        pause_manager: PauseManager | None = None,
    ) -> None:
        self._context = context
        self._scheduler = scheduler
        self._auth = auth
        self._send = send_fn  # send_fn(platform, channel, content)
        self._memory_store = memory_store
        self._pause_manager = pause_manager

    async def handle(
        self, platform: str, channel: str, user_id: str, content: str
    ) -> None:
        parts = content.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "/forget":
            count = await self._context.forget(platform, channel)
            await self._send(platform, channel, f"Cleared {count} messages from context.")

        elif command == "/context":
            stats = await self._context.get_stats(platform, channel)
            await self._send(
                platform, channel,
                f"Context: {stats['message_count']} messages, {stats['total_chars']} chars",
            )

        elif command == "/summarize":
            summary = await self._context.summarize(platform, channel)
            if summary:
                await self._send(platform, channel, f"**Summary:**\n{summary}")
            else:
                await self._send(platform, channel, "No context to summarize.")

        elif command == "/jobs":
            jobs = await self._scheduler.list_jobs()
            if not jobs:
                await self._send(platform, channel, "No scheduled jobs.")
                return
            lines = [f"**{j.name}** — `{j.cron_expr}` — {j.action}" for j in jobs]
            await self._send(platform, channel, "\n".join(lines))

        elif command == "/sudo":
            await self._handle_sudo(platform, channel, user_id, args)

        elif command == "/memory":
            await self._handle_memory(platform, channel, user_id, args)

        elif command == "/pause":
            await self._handle_pause(platform, channel, user_id, args)

        elif command == "/resume":
            await self._handle_resume(platform, channel, user_id)

        elif command == "/status":
            await self._handle_status(platform, channel)

        elif command == "/help":
            await self._send(
                platform, channel,
                "**Commands:** /forget, /context, /summarize, /jobs, /sudo, /memory, /pause, /resume, /status, /help",
            )
        else:
            await self._send(platform, channel, f"Unknown command: {command}")

    async def _handle_sudo(
        self, platform: str, channel: str, user_id: str, args: str
    ) -> None:
        if not args:
            # List pending sudo requests (admin only)
            if self._auth.check_permission(platform, user_id, PermissionLevel.ADMIN):
                pending = self._auth.list_pending_sudo()
                if not pending:
                    await self._send(platform, channel, "No pending sudo requests.")
                else:
                    lines = [
                        f"`{p['request_id']}` — {p['platform']}:{p['user_id']} → {p['requested_level']} — {p['action']}"
                        for p in pending
                    ]
                    await self._send(platform, channel, "**Pending sudo requests:**\n" + "\n".join(lines))
            else:
                await self._send(platform, channel, "Admin access required to view sudo requests.")
        elif args.startswith("approve "):
            request_id = args.split()[1]
            if self._auth.approve_sudo(request_id, platform, user_id):
                await self._send(platform, channel, f"Sudo request `{request_id}` approved.")
            else:
                await self._send(platform, channel, "Failed to approve. Check request ID and your permissions.")
        elif args.startswith("deny "):
            request_id = args.split()[1]
            if self._auth.deny_sudo(request_id):
                await self._send(platform, channel, f"Sudo request `{request_id}` denied.")
            else:
                await self._send(platform, channel, f"Request `{request_id}` not found.")
        else:
            # User requesting sudo
            request_id = await self._auth.request_sudo(platform, user_id, args)
            await self._send(
                platform, channel,
                f"Sudo requested (`{request_id}`). An admin must approve with `/sudo approve {request_id}`.",
            )

    async def _handle_memory(
        self, platform: str, channel: str, user_id: str, args: str
    ) -> None:
        if not self._memory_store:
            await self._send(platform, channel, "Memory store not configured.")
            return

        if args.startswith("search "):
            query = args[7:].strip()
            results = await self._memory_store.search(query)
            if not results:
                await self._send(platform, channel, f"No memories matching '{query}'.")
            else:
                lines = [f"**{r['key']}**: {r['value']} ({r['category']})" for r in results[:20]]
                await self._send(platform, channel, "\n".join(lines))
        elif args.strip() == "clear":
            if not self._auth.check_permission(platform, user_id, PermissionLevel.ADMIN):
                await self._send(platform, channel, "Admin access required to clear memory.")
                return
            count = await self._memory_store.clear()
            await self._send(platform, channel, f"Cleared {count} memories.")
        else:
            export = await self._memory_store.export_context()
            if not export:
                await self._send(platform, channel, "No memories stored.")
            else:
                await self._send(platform, channel, f"**Memories:**\n{export}")

    async def _handle_pause(
        self, platform: str, channel: str, user_id: str, args: str
    ) -> None:
        if not self._auth.check_permission(platform, user_id, PermissionLevel.OPERATOR):
            await self._send(platform, channel, "Operator access required.")
            return
        if not self._pause_manager:
            await self._send(platform, channel, "Pause manager not configured.")
            return

        duration = parse_duration(args.strip()) if args.strip() else None
        self._pause_manager.pause(duration_seconds=duration)

        if duration:
            await self._send(
                platform, channel,
                f"Paused for {args.strip()}. I'll still respond if you message me directly.",
            )
        else:
            await self._send(
                platform, channel,
                "Paused indefinitely. Use /resume to resume. I'll still respond to direct messages.",
            )

    async def _handle_resume(
        self, platform: str, channel: str, user_id: str
    ) -> None:
        if not self._auth.check_permission(platform, user_id, PermissionLevel.OPERATOR):
            await self._send(platform, channel, "Operator access required.")
            return
        if not self._pause_manager:
            await self._send(platform, channel, "Pause manager not configured.")
            return

        count = self._pause_manager.resume()
        self._pause_manager.drain_queue()
        if count:
            await self._send(platform, channel, f"Resumed. {count} queued event(s) were missed.")
        else:
            await self._send(platform, channel, "Resumed.")

    async def _handle_status(self, platform: str, channel: str) -> None:
        if self._pause_manager and self._pause_manager.is_paused:
            queued = len(self._pause_manager.queued_events)
            await self._send(
                platform, channel,
                f"Status: **Paused** | {queued} queued event(s)",
            )
        else:
            await self._send(platform, channel, "Status: **Active**")
