"""Shell command execution tool."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger
from shannon.utils.platform import get_default_shell, get_platform

log = get_logger(__name__)

# Patterns that are always blocked
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-rf\s+/\s*$", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+.*of=/dev/", re.IGNORECASE),
    re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
    re.compile(r":(){ :\|:& };:", re.IGNORECASE),  # fork bomb
]

_DEFAULT_TIMEOUT = 30


class ShellTool(BaseTool):
    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command on the host system. "
            "Returns stdout, stderr, and exit code. "
            "Use for system tasks, file operations, and running programs."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30, max 300).",
                    "default": _DEFAULT_TIMEOUT,
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command.",
                },
            },
            "required": ["command"],
        }

    @property
    def required_permission(self) -> int:
        return 2  # operator

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs["command"]
        timeout: int = min(kwargs.get("timeout", _DEFAULT_TIMEOUT), 300)
        working_dir: str | None = kwargs.get("working_dir")

        # Check blocklist
        for pattern in _BLOCKED_PATTERNS:
            if pattern.search(command):
                log.warning("blocked_command", command=command)
                return ToolResult(
                    success=False,
                    error=f"Command blocked by safety filter: {command}",
                )

        log.info("shell_exec", command=command, timeout=timeout)

        shell = get_default_shell()
        platform = get_platform()

        if platform == "windows":
            args = ["powershell", "-NoProfile", "-Command", command]
        else:
            args = [shell, "-c", command]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout}s",
                )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Truncate very long output
            max_len = 4000
            if len(stdout_str) > max_len:
                stdout_str = stdout_str[:max_len] + f"\n... (truncated, {len(stdout_str)} total chars)"
            if len(stderr_str) > max_len:
                stderr_str = stderr_str[:max_len] + f"\n... (truncated, {len(stderr_str)} total chars)"

            success = proc.returncode == 0
            output_parts = []
            if stdout_str:
                output_parts.append(stdout_str)
            if stderr_str:
                output_parts.append(f"STDERR:\n{stderr_str}")
            output_parts.append(f"Exit code: {proc.returncode}")

            return ToolResult(
                success=success,
                output="\n".join(output_parts),
                error=stderr_str if not success else "",
                data={"exit_code": proc.returncode},
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Shell not found: {shell}",
            )
        except Exception as e:
            log.exception("shell_exec_error")
            return ToolResult(success=False, error=str(e))
