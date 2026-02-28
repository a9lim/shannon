"""Interactive CLI program driver using PTY (Unix) or pywinpty (Windows)."""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from shannon.config import InteractiveConfig
from shannon.core.auth import PermissionLevel
from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Session:
    session_id: str
    command: str
    process: Any  # pexpect.spawn or winpty process
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


class InteractiveTool(BaseTool):
    """Start and interact with interactive command-line programs."""

    def __init__(self, config: InteractiveConfig | None = None) -> None:
        self._config = config or InteractiveConfig()
        self._sessions: dict[str, Session] = {}
        self._next_id = 1

    @property
    def name(self) -> str:
        return "interactive"

    @property
    def description(self) -> str:
        return (
            "Start and interact with interactive CLI programs (python, node, ssh, etc.). "
            "Supports starting sessions, sending input, reading output, waiting for patterns, "
            "and closing sessions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "send", "read", "expect", "close", "list"],
                    "description": "The action to perform.",
                },
                "command": {
                    "type": "string",
                    "description": "Command to launch (for 'start' action).",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (for send/read/expect/close).",
                },
                "input": {
                    "type": "string",
                    "description": "Input to send to the program.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to wait for (for 'expect' action).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds.",
                    "default": 10,
                },
            },
            "required": ["action"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.OPERATOR

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")

        # Clean up idle sessions first
        await self._cleanup_idle()

        try:
            if action == "start":
                return await self._start(kwargs.get("command", ""))
            elif action == "send":
                return await self._send(kwargs.get("session_id", ""), kwargs.get("input", ""))
            elif action == "read":
                return await self._read(kwargs.get("session_id", ""), kwargs.get("timeout", 10))
            elif action == "expect":
                return await self._expect(
                    kwargs.get("session_id", ""),
                    kwargs.get("pattern", ""),
                    kwargs.get("timeout", 10),
                )
            elif action == "close":
                return await self._close(kwargs.get("session_id", ""))
            elif action == "list":
                return self._list_sessions()
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            log.exception("interactive_error", action=action)
            return ToolResult(success=False, error=str(e))

    async def _start(self, command: str) -> ToolResult:
        if not command:
            return ToolResult(success=False, error="Command is required")

        if len(self._sessions) >= self._config.max_sessions:
            return ToolResult(
                success=False,
                error=f"Maximum {self._config.max_sessions} concurrent sessions reached. Close one first.",
            )

        session_id = f"s{self._next_id}"
        self._next_id += 1

        try:
            if sys.platform == "win32":
                process = await self._start_windows(command)
            else:
                process = await self._start_unix(command)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to start: {e}")

        session = Session(session_id=session_id, command=command, process=process)
        self._sessions[session_id] = session
        log.info("interactive_session_started", session_id=session_id, command=command)

        return ToolResult(
            success=True,
            output=f"Session '{session_id}' started with command: {command}",
            data={"session_id": session_id},
        )

    async def _start_unix(self, command: str) -> Any:
        import pexpect  # type: ignore[import-untyped]
        child = pexpect.spawn(command, encoding="utf-8", timeout=30)
        child.setwinsize(40, 120)
        return child

    async def _start_windows(self, command: str) -> Any:
        # Use pexpect.popen_spawn on Windows (no PTY, but works for many programs)
        import pexpect.popen_spawn  # type: ignore[import-untyped]
        child = pexpect.popen_spawn.PopenSpawn(command, encoding="utf-8", timeout=30)
        return child

    async def _send(self, session_id: str, input_text: str) -> ToolResult:
        session = self._sessions.get(session_id)
        if not session:
            return ToolResult(success=False, error=f"Session '{session_id}' not found")

        session.last_active = time.time()

        def _do_send() -> None:
            session.process.sendline(input_text)

        await asyncio.to_thread(_do_send)
        return ToolResult(success=True, output=f"Sent to {session_id}: {input_text}")

    async def _read(self, session_id: str, timeout: int) -> ToolResult:
        session = self._sessions.get(session_id)
        if not session:
            return ToolResult(success=False, error=f"Session '{session_id}' not found")

        session.last_active = time.time()

        import pexpect  # type: ignore[import-untyped]

        def _do_read() -> str:
            try:
                session.process.expect(pexpect.TIMEOUT, timeout=min(timeout, 30))
            except pexpect.TIMEOUT:
                pass
            before = session.process.before
            if before is None:
                return ""
            return str(before)

        output = await asyncio.to_thread(_do_read)
        # Truncate
        if len(output) > self._config.max_output_size:
            output = output[-self._config.max_output_size:]

        return ToolResult(success=True, output=output)

    async def _expect(self, session_id: str, pattern: str, timeout: int) -> ToolResult:
        if not pattern:
            return ToolResult(success=False, error="Pattern is required")

        session = self._sessions.get(session_id)
        if not session:
            return ToolResult(success=False, error=f"Session '{session_id}' not found")

        session.last_active = time.time()

        import pexpect  # type: ignore[import-untyped]

        def _do_expect() -> tuple[bool, str]:
            try:
                session.process.expect(pattern, timeout=min(timeout, 60))
                before = session.process.before or ""
                after = session.process.after or ""
                return True, f"{before}{after}"
            except pexpect.TIMEOUT:
                before = session.process.before or ""
                return False, f"Timeout waiting for pattern. Output so far:\n{before}"
            except pexpect.EOF:
                before = session.process.before or ""
                return False, f"Process exited. Final output:\n{before}"

        found, output = await asyncio.to_thread(_do_expect)
        return ToolResult(success=found, output=str(output))

    async def _close(self, session_id: str) -> ToolResult:
        session = self._sessions.pop(session_id, None)
        if not session:
            return ToolResult(success=False, error=f"Session '{session_id}' not found")

        try:
            if hasattr(session.process, "close"):
                session.process.close(force=True)
            elif hasattr(session.process, "kill"):
                session.process.kill(9)
        except Exception:
            pass

        log.info("interactive_session_closed", session_id=session_id)
        return ToolResult(success=True, output=f"Session '{session_id}' closed")

    def _list_sessions(self) -> ToolResult:
        if not self._sessions:
            return ToolResult(success=True, output="No active sessions")
        lines = []
        for sid, s in self._sessions.items():
            age = int(time.time() - s.created_at)
            idle = int(time.time() - s.last_active)
            lines.append(f"  {sid}: {s.command} (age: {age}s, idle: {idle}s)")
        return ToolResult(success=True, output="Active sessions:\n" + "\n".join(lines))

    async def _cleanup_idle(self) -> None:
        now = time.time()
        to_remove = [
            sid for sid, s in self._sessions.items()
            if now - s.last_active > self._config.idle_timeout
        ]
        for sid in to_remove:
            log.info("interactive_session_idle_timeout", session_id=sid)
            await self._close(sid)

    async def cleanup(self) -> None:
        """Close all sessions."""
        for sid in list(self._sessions.keys()):
            await self._close(sid)
