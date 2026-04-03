"""Persistent bash session executor for the bash_20250124 tool."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from shannon.config import BashConfig

_MAX_OUTPUT = 10_000  # characters


class BashExecutor:
    """Maintains a persistent /bin/bash subprocess across multiple execute() calls.

    Environment variables and the working directory persist between calls.
    """

    def __init__(self, config: BashConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> asyncio.subprocess.Process:
        """Start a new bash subprocess if one isn't already running."""
        if self._process is None or self._process.returncode is not None:
            self._process = await asyncio.create_subprocess_exec(
                "/bin/bash", "--norc", "--noprofile",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        return self._process

    def _check_blocklist(self, command: str) -> str | None:
        """Return an error string if the command matches a blocklist entry, else None.

        NOTE: This is a simple substring check and can be bypassed by obfuscation
        (e.g., variable expansion, path aliases). It is a convenience filter, not a
        security boundary. The real protection is ``require_confirmation``, which
        prompts the user before executing any command.
        """
        for pattern in self._config.blocklist:
            if pattern in command:
                return f"Command not allowed: matches blocklist pattern '{pattern}'"
        return None

    async def _read_until_sentinel(
        self, process: asyncio.subprocess.Process, sentinel: str
    ) -> str:
        """Read stdout lines until the sentinel marker appears."""
        lines: list[str] = []
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                # Process died before we saw the sentinel
                break
            decoded = line.decode(errors="replace")
            if sentinel in decoded:
                break
            lines.append(decoded)
        return "".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, params: dict[str, Any]) -> str:
        """Execute a command or handle a restart request.

        Supported params:
          - command (str): shell command to run
          - restart (bool): if truthy, terminate current session and start fresh
        """
        async with self._lock:
            # --- restart ---
            if params.get("restart"):
                await self._terminate()
                await self._ensure_session()
                return "Session restarted."

            command = params.get("command")
            if not command:
                return "Error: no 'command' provided."

            # --- blocklist check ---
            blocked = self._check_blocklist(command)
            if blocked:
                return blocked

            # --- run command ---
            try:
                process = await self._ensure_session()
            except Exception as exc:
                return f"Error starting bash session: {exc}"

            # Use a unique sentinel to detect end of output
            sentinel = f"__SENTINEL_{uuid.uuid4().hex}__"
            payload = f"{command}\necho '{sentinel}'\n"

            assert process.stdin is not None
            try:
                process.stdin.write(payload.encode())
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                # Process died mid-write; restart and report
                self._process = None
                return "Error: bash session terminated unexpectedly."

            # Read with timeout
            timeout = self._config.timeout_seconds
            try:
                output = await asyncio.wait_for(
                    self._read_until_sentinel(process, sentinel),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Kill the hung process and reset so future calls get a fresh shell
                await self._terminate()
                return f"Command timed out after {timeout} seconds."

            # Check if process died (non-zero returncode without us killing it)
            if process.returncode is not None:
                self._process = None
                if not output:
                    output = f"Process exited with code {process.returncode}."

            # Truncate large output
            if len(output) > _MAX_OUTPUT:
                output = output[:_MAX_OUTPUT] + f"\n[Output truncated at {_MAX_OUTPUT} characters]"

            return output

    async def close(self) -> None:
        """Terminate the bash subprocess."""
        async with self._lock:
            await self._terminate()

    async def _terminate(self) -> None:
        """Terminate subprocess without acquiring the lock (call within lock)."""
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
        self._process = None
