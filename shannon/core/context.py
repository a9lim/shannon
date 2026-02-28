"""Conversation context manager with SQLite persistence and LLM summarization."""

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

_SUMMARIZE_PROMPT = (
    "Summarize the following conversation history concisely. "
    "Preserve key facts, decisions, and context that would be needed to continue the conversation. "
    "Keep the summary under 500 words."
)


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

        # Trim or summarize if exceeding token budget
        if self._llm and messages:
            messages = await self._fit_to_token_limit(messages, platform, channel)

        return messages

    def _count_message_tokens(self, msg: LLMMessage) -> int:
        """Count tokens in a single message."""
        assert self._llm is not None
        text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        return self._llm.count_tokens(text)

    def _total_tokens(self, messages: list[LLMMessage]) -> int:
        return sum(self._count_message_tokens(m) for m in messages)

    async def _fit_to_token_limit(
        self, messages: list[LLMMessage], platform: str, channel: str
    ) -> list[LLMMessage]:
        """Summarize or trim messages to stay within token budget."""
        assert self._llm is not None
        total = self._total_tokens(messages)

        if total <= self._max_context_tokens:
            return messages

        # Try summarization: summarize the oldest half and keep the newest half
        split_point = len(messages) // 2
        old_messages = messages[:split_point]
        recent_messages = messages[split_point:]

        # Build text from old messages for summarization
        summary_text = "\n".join(
            f"{m.role}: {m.content if isinstance(m.content, str) else '[structured]'}"
            for m in old_messages
        )

        try:
            summary_response = await self._llm.complete(
                messages=[LLMMessage(role="user", content=f"{_SUMMARIZE_PROMPT}\n\n{summary_text}")],
                max_tokens=1024,
                temperature=0.3,
            )
            summary = summary_response.content

            # Replace old messages with summary
            summary_msg = LLMMessage(
                role="user",
                content=f"[Previous conversation summary: {summary}]",
            )
            messages = [summary_msg] + recent_messages

            log.info(
                "context_summarized",
                platform=platform,
                channel=channel,
                old_count=len(old_messages),
                new_token_count=self._total_tokens(messages),
            )
        except Exception:
            log.exception("context_summarization_failed")
            # Fall back to simple trimming
            messages = recent_messages

        # Final trim if still over budget
        total = self._total_tokens(messages)
        while total > self._max_context_tokens and len(messages) > 1:
            dropped = messages.pop(0)
            total -= self._count_message_tokens(dropped)

        return messages

    async def summarize(self, platform: str, channel: str) -> str | None:
        """Explicitly summarize current context. Returns summary text."""
        assert self._db is not None
        if not self._llm:
            return None

        cursor = await self._db.execute(
            "SELECT role, content FROM messages "
            "WHERE platform = ? AND channel = ? "
            "ORDER BY timestamp ASC",
            (platform, channel),
        )
        rows = await cursor.fetchall()
        if not rows:
            return None

        text = "\n".join(f"{row[0]}: {row[1]}" for row in rows)
        try:
            response = await self._llm.complete(
                messages=[LLMMessage(role="user", content=f"{_SUMMARIZE_PROMPT}\n\n{text}")],
                max_tokens=1024,
                temperature=0.3,
            )
            return response.content
        except Exception:
            log.exception("explicit_summarization_failed")
            return None

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
