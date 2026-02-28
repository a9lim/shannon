"""Tests for slash command dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shannon.core.commands import CommandHandler


@pytest.fixture
def send_fn():
    return AsyncMock()


@pytest.fixture
def context():
    ctx = AsyncMock()
    ctx.forget = AsyncMock(return_value=5)
    ctx.get_stats = AsyncMock(return_value={"message_count": 10, "total_chars": 2000})
    ctx.summarize = AsyncMock(return_value="A summary of the conversation.")
    return ctx


@pytest.fixture
def scheduler():
    sched = AsyncMock()
    sched.list_jobs = AsyncMock(return_value=[])
    return sched


@pytest.fixture
def auth():
    a = MagicMock()
    a.check_permission = MagicMock(return_value=False)
    a.list_pending_sudo = MagicMock(return_value=[])
    a.approve_sudo = MagicMock(return_value=True)
    a.deny_sudo = MagicMock(return_value=True)
    a.request_sudo = AsyncMock(return_value="sudo-abc123")
    return a


@pytest.fixture
def handler(context, scheduler, auth, send_fn):
    return CommandHandler(context, scheduler, auth, send_fn)


class TestCommandHandler:
    async def test_forget(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/forget")
        send_fn.assert_awaited_once()
        assert "Cleared 5" in send_fn.call_args[0][2]

    async def test_context(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/context")
        send_fn.assert_awaited_once()
        assert "10 messages" in send_fn.call_args[0][2]

    async def test_summarize(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/summarize")
        send_fn.assert_awaited_once()
        assert "Summary" in send_fn.call_args[0][2]

    async def test_summarize_empty(self, handler, send_fn, context):
        context.summarize.return_value = None
        await handler.handle("discord", "ch1", "user1", "/summarize")
        assert "No context" in send_fn.call_args[0][2]

    async def test_jobs_empty(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/jobs")
        assert "No scheduled jobs" in send_fn.call_args[0][2]

    async def test_help(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/help")
        assert "/forget" in send_fn.call_args[0][2]

    async def test_unknown_command(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/foobar")
        assert "Unknown command" in send_fn.call_args[0][2]

    async def test_sudo_request(self, handler, send_fn):
        await handler.handle("discord", "ch1", "user1", "/sudo run dangerous command")
        assert "sudo-abc123" in send_fn.call_args[0][2]

    async def test_sudo_approve(self, handler, send_fn, auth):
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "admin1", "/sudo approve sudo-abc123")
        auth.approve_sudo.assert_called_once_with("sudo-abc123", "discord", "admin1")
        assert "approved" in send_fn.call_args[0][2]

    async def test_sudo_deny(self, handler, send_fn, auth):
        await handler.handle("discord", "ch1", "admin1", "/sudo deny sudo-abc123")
        auth.deny_sudo.assert_called_once_with("sudo-abc123")
        assert "denied" in send_fn.call_args[0][2]
