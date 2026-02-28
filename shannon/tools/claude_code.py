"""Delegate tasks to Claude Code CLI."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class ClaudeCodeTool(BaseTool):
    @property
    def name(self) -> str:
        return "claude_code"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to Claude Code for complex coding, file manipulation, "
            "or multi-step technical work. Claude Code runs as a subprocess and can "
            "read/write files, run commands, and perform sophisticated code changes."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task description to send to Claude Code.",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for file operations.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 300, max 600).",
                    "default": 300,
                },
            },
            "required": ["task"],
        }

    @property
    def required_permission(self) -> int:
        return 2  # operator

    async def execute(self, **kwargs: Any) -> ToolResult:
        task: str = kwargs["task"]
        working_dir: str | None = kwargs.get("working_dir")
        timeout: int = min(kwargs.get("timeout", 300), 600)

        log.info("claude_code_delegating", task=task[:100], timeout=timeout)

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "--print",
                "--output-format", "json",
                task,
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
                    error=f"Claude Code timed out after {timeout}s",
                )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Try to parse JSON output
            try:
                result_data = json.loads(stdout_str)
                output = result_data.get("result", stdout_str)
                if isinstance(output, dict):
                    output = json.dumps(output, indent=2)
            except json.JSONDecodeError:
                output = stdout_str

            # Truncate very long output
            max_len = 8000
            if len(output) > max_len:
                output = output[:max_len] + f"\n... (truncated, {len(output)} total chars)"

            success = proc.returncode == 0
            if stderr_str and not success:
                output = f"{output}\n\nSTDERR:\n{stderr_str}" if output else stderr_str

            return ToolResult(
                success=success,
                output=output,
                error=stderr_str if not success else "",
                data={"exit_code": proc.returncode},
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="Claude Code CLI ('claude') not found. Is it installed and on PATH?",
            )
        except Exception as e:
            log.exception("claude_code_error")
            return ToolResult(success=False, error=str(e))
