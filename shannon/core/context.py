"""Conversation context manager with SQLite persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from shannon.core.llm import LLMMessage, LLMProvider
from shannon.utils.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_lookup
    ON messages (platform, channel, user_id, timestamp);
"""


class ContextManager:
    def __init__(
        self,
        db_path: Path,
        max_messages: int = 50,
        llm: LLMProvider | None = None,
        max_context_tokens: int = 100_000,
    ) -> None:
        self._db_path = db_path
        self._max_messages = max_messages
        self._llm = llm
        self._max_context_tokens = max_context_tokens
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def add_message(
        self,
        platform: str,
        channel: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO messages (platform, channel, user_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (platform, channel, user_id, role, content, now),
        )
        await self._db.commit()

    async def get_context(
        self, platform: str, channel: str, user_id: str
    ) -> list[LLMMessage]:
        """Get recent conversation history as LLM messages."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT role, content FROM messages "
            "WHERE platform = ? AND channel = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (platform, channel, self._max_messages),
        )
        rows = await cursor.fetchall()
        rows.reverse()  # Oldest first

        messages = [LLMMessage(role=row[0], content=row[1]) for row in rows]

        # Trim if exceeding token budget
        if self._llm:
            messages = self._trim_to_token_limit(messages)

        return messages

    def _trim_to_token_limit(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Drop oldest messages to stay within token budget."""
        assert self._llm is not None
        total = sum(
            self._llm.count_tokens(
                m.content if isinstance(m.content, str) else json.dumps(m.content)
            )
            for m in messages
        )
        while total > self._max_context_tokens and len(messages) > 1:
            dropped = messages.pop(0)
            total -= self._llm.count_tokens(
                dropped.content if isinstance(dropped.content, str) else json.dumps(dropped.content)
            )
        return messages

    async def forget(self, platform: str, channel: str) -> int:
        """Clear context for a channel. Returns number of messages deleted."""
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM messages WHERE platform = ? AND channel = ?",
            (platform, channel),
        )
        await self._db.commit()
        return cursor.rowcount

    async def get_stats(self, platform: str, channel: str) -> dict[str, int]:
        """Get context stats for a channel."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(content)), 0) "
            "FROM messages WHERE platform = ? AND channel = ?",
            (platform, channel),
        )
        row = await cursor.fetchone()
        assert row is not None
        return {"message_count": row[0], "total_chars": row[1]}
