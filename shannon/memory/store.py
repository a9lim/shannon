"""Persistent key-value memory store with SQLite backend."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from shannon.utils.logging import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT DEFAULT ''
);
"""


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
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

    async def set(
        self,
        key: str,
        value: str,
        category: str = "general",
        source: str = "",
    ) -> None:
        """Upsert a key-value pair into memory."""
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO memory (key, value, category, created_at, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, "
            "category = excluded.category, "
            "updated_at = excluded.updated_at, "
            "source = excluded.source",
            (key, value, category, now, now, source),
        )
        await self._db.commit()

    async def get(self, key: str) -> dict | None:
        """Retrieve a memory entry by key."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category, created_at, updated_at, source "
            "FROM memory WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "key": row[0],
            "value": row[1],
            "category": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "source": row[5],
        }

    async def delete(self, key: str) -> bool:
        """Delete a memory entry. Returns True if an entry was deleted."""
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM memory WHERE key = ?",
            (key,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def search(self, query: str) -> list[dict]:
        """Search memory by key or value using LIKE matching."""
        assert self._db is not None
        pattern = f"%{query}%"
        cursor = await self._db.execute(
            "SELECT key, value, category, created_at, updated_at, source "
            "FROM memory WHERE key LIKE ? OR value LIKE ? "
            "ORDER BY updated_at DESC",
            (pattern, pattern),
        )
        rows = await cursor.fetchall()
        return [
            {
                "key": row[0],
                "value": row[1],
                "category": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                "source": row[5],
            }
            for row in rows
        ]

    async def list_category(self, category: str) -> list[dict]:
        """List all memory entries in a category."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category, created_at, updated_at, source "
            "FROM memory WHERE category = ? "
            "ORDER BY updated_at DESC",
            (category,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "key": row[0],
                "value": row[1],
                "category": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                "source": row[5],
            }
            for row in rows
        ]

    async def clear(self) -> int:
        """Delete all memory entries. Returns the count of deleted entries."""
        assert self._db is not None
        cursor = await self._db.execute("DELETE FROM memory")
        await self._db.commit()
        return cursor.rowcount

    async def export_context(self, max_tokens: int = 2000) -> str:
        """Export all memories as formatted text, truncated at max_tokens*4 chars."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category FROM memory ORDER BY category, key"
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""

        max_chars = max_tokens * 4
        lines: list[str] = []
        total_chars = 0
        for row in rows:
            line = f"[{row[2]}] {row[0]}: {row[1]}"
            if total_chars + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total_chars += len(line) + 1  # +1 for newline

        return "\n".join(lines)
