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


class TestMemoryCommands:
    @pytest.fixture
    def handler_with_memory(self, context, scheduler, auth, send_fn):
        memory = AsyncMock()
        return CommandHandler(context, scheduler, auth, send_fn, memory_store=memory), memory

    async def test_memory_list(self, handler_with_memory, send_fn):
        handler, memory = handler_with_memory
        memory.export_context = AsyncMock(return_value="[identity] name: Shannon")
        await handler.handle("discord", "ch1", "user1", "/memory")
        send_fn.assert_awaited()
        assert "Shannon" in send_fn.call_args[0][2]

    async def test_memory_list_empty(self, handler_with_memory, send_fn):
        handler, memory = handler_with_memory
        memory.export_context = AsyncMock(return_value="")
        await handler.handle("discord", "ch1", "user1", "/memory")
        assert "No memories" in send_fn.call_args[0][2]

    async def test_memory_search(self, handler_with_memory, send_fn):
        handler, memory = handler_with_memory
        memory.search = AsyncMock(return_value=[
            {"key": "color", "value": "blue", "category": "prefs"},
        ])
        await handler.handle("discord", "ch1", "user1", "/memory search color")
        assert "blue" in send_fn.call_args[0][2]

    async def test_memory_search_empty(self, handler_with_memory, send_fn):
        handler, memory = handler_with_memory
        memory.search = AsyncMock(return_value=[])
        await handler.handle("discord", "ch1", "user1", "/memory search xyz")
        assert "No memories" in send_fn.call_args[0][2]

    async def test_memory_clear_requires_admin(self, handler_with_memory, send_fn, auth):
        handler, memory = handler_with_memory
        auth.check_permission.return_value = False
        await handler.handle("discord", "ch1", "user1", "/memory clear")
        assert "Admin" in send_fn.call_args[0][2]

    async def test_memory_clear_admin(self, handler_with_memory, send_fn, auth):
        handler, memory = handler_with_memory
        auth.check_permission.return_value = True
        memory.clear = AsyncMock(return_value=5)
        await handler.handle("discord", "ch1", "admin1", "/memory clear")
        assert "Cleared 5" in send_fn.call_args[0][2]


from shannon.core.pause import PauseManager


class TestPauseCommands:
    @pytest.fixture
    def handler_with_pause(self, context, scheduler, auth, send_fn):
        pm = PauseManager()
        return CommandHandler(context, scheduler, auth, send_fn, pause_manager=pm), pm

    async def test_pause_command(self, handler_with_pause, send_fn, auth):
        handler, pm = handler_with_pause
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/pause")
        assert pm.is_paused is True
        send_fn.assert_awaited()
        assert "Paused" in send_fn.call_args[0][2]

    async def test_pause_with_duration(self, handler_with_pause, send_fn, auth):
        handler, pm = handler_with_pause
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/pause 2h")
        assert pm.is_paused is True
        assert "2h" in send_fn.call_args[0][2]

    async def test_pause_requires_operator(self, handler_with_pause, send_fn, auth):
        handler, pm = handler_with_pause
        auth.check_permission.return_value = False
        await handler.handle("discord", "ch1", "user1", "/pause")
        assert pm.is_paused is False
        assert "Operator" in send_fn.call_args[0][2]

    async def test_resume_command(self, handler_with_pause, send_fn, auth):
        handler, pm = handler_with_pause
        pm.pause()
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/resume")
        assert pm.is_paused is False
        assert "Resumed" in send_fn.call_args[0][2]

    async def test_resume_with_queued(self, handler_with_pause, send_fn, auth):
        handler, pm = handler_with_pause
        pm.pause()
        pm.queue_event({"data": "test1"})
        pm.queue_event({"data": "test2"})
        auth.check_permission.return_value = True
        await handler.handle("discord", "ch1", "op1", "/resume")
        assert "2 queued" in send_fn.call_args[0][2]

    async def test_status_active(self, handler_with_pause, send_fn):
        handler, pm = handler_with_pause
        await handler.handle("discord", "ch1", "user1", "/status")
        assert "Active" in send_fn.call_args[0][2]

    async def test_status_paused(self, handler_with_pause, send_fn):
        handler, pm = handler_with_pause
        pm.pause()
        await handler.handle("discord", "ch1", "user1", "/status")
        assert "Paused" in send_fn.call_args[0][2]
