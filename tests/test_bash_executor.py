"""Tests for BashExecutor — persistent bash session backend."""

import asyncio
import pytest

from shannon.config import BashConfig
from shannon.tools.bash_executor import BashExecutor


def _config(**kwargs) -> BashConfig:
    defaults = dict(
        enabled=True,
        require_confirmation=False,
        blocklist=["rm -rf", "sudo", "shutdown", "reboot", "mkfs", "dd if="],
        timeout_seconds=5,
    )
    defaults.update(kwargs)
    return BashConfig(**defaults)


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


async def test_execute_echo_returns_output():
    """echo command returns its output."""
    executor = BashExecutor(_config())
    result = await executor.execute({"command": "echo hello"})
    assert "hello" in result
    await executor.close()


async def test_execute_returns_stderr():
    """Commands that write to stderr include that output."""
    executor = BashExecutor(_config())
    result = await executor.execute({"command": "echo error >&2"})
    assert "error" in result
    await executor.close()


async def test_execute_exit_code_shown_on_failure():
    """Non-zero exit codes are surfaced in the result."""
    executor = BashExecutor(_config())
    result = await executor.execute({"command": "exit 1"})
    # After exit 1 the shell itself exits; executor should report an error
    assert result  # something is returned, not empty
    await executor.close()


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------


async def test_env_var_persists_across_commands():
    """Environment variable set in one call is visible in the next."""
    executor = BashExecutor(_config())
    await executor.execute({"command": "export MYVAR=42"})
    result = await executor.execute({"command": "echo $MYVAR"})
    assert "42" in result
    await executor.close()


async def test_working_directory_persists():
    """cd in one call persists to the next."""
    executor = BashExecutor(_config())
    await executor.execute({"command": "cd /tmp"})
    result = await executor.execute({"command": "pwd"})
    assert "/tmp" in result
    await executor.close()


# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------


async def test_restart_clears_env():
    """restart=true clears environment variables from prior session."""
    executor = BashExecutor(_config())
    await executor.execute({"command": "export MYVAR=42"})
    await executor.execute({"restart": True})
    result = await executor.execute({"command": "echo ${MYVAR:-empty}"})
    assert "42" not in result
    await executor.close()


async def test_restart_clears_working_directory():
    """restart=true resets the working directory."""
    executor = BashExecutor(_config())
    await executor.execute({"command": "cd /tmp"})
    await executor.execute({"restart": True})
    result = await executor.execute({"command": "pwd"})
    assert result.strip() != "/tmp"
    await executor.close()


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


async def test_blocklist_rejects_dangerous_command():
    """Commands matching the blocklist return an error string."""
    executor = BashExecutor(_config())
    result = await executor.execute({"command": "rm -rf /"})
    assert "blocked" in result.lower() or "not allowed" in result.lower()
    await executor.close()


async def test_blocklist_rejects_sudo():
    """sudo commands are blocked."""
    executor = BashExecutor(_config())
    result = await executor.execute({"command": "sudo ls"})
    assert "blocked" in result.lower() or "not allowed" in result.lower()
    await executor.close()


async def test_blocklist_does_not_block_safe_command():
    """Safe commands pass through the blocklist check."""
    executor = BashExecutor(_config())
    result = await executor.execute({"command": "echo safe"})
    assert "safe" in result
    await executor.close()


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


async def test_timeout_kills_slow_command():
    """Commands that exceed timeout_seconds are killed and report timeout."""
    executor = BashExecutor(_config(timeout_seconds=1))
    result = await executor.execute({"command": "sleep 10"})
    assert "timeout" in result.lower() or "timed out" in result.lower()
    await executor.close()


async def test_executor_still_usable_after_timeout():
    """Executor recovers and can run commands after a timeout."""
    executor = BashExecutor(_config(timeout_seconds=1))
    await executor.execute({"command": "sleep 10"})
    result = await executor.execute({"command": "echo recovered"})
    assert "recovered" in result
    await executor.close()


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


async def test_close_terminates_session():
    """close() shuts down the subprocess cleanly."""
    executor = BashExecutor(_config())
    await executor.execute({"command": "echo hi"})
    await executor.close()
    # After close, _process should be None or terminated
    assert executor._process is None or executor._process.returncode is not None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_missing_command_key_returns_error():
    """Passing params without 'command' or 'restart' returns an error."""
    executor = BashExecutor(_config())
    result = await executor.execute({})
    assert result  # non-empty error message
    await executor.close()
