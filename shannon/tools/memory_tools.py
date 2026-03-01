"""Memory management tools for persistent key-value storage."""

from __future__ import annotations

from typing import Any

from shannon.core.auth import PermissionLevel
from shannon.memory.store import MemoryStore
from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class MemorySetTool(BaseTool):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "memory_set"

    @property
    def description(self) -> str:
        return "Store a key-value pair in persistent memory. Survives restarts."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key to store the value under.",
                },
                "value": {
                    "type": "string",
                    "description": "The value to store.",
                },
                "category": {
                    "type": "string",
                    "description": "Category for organizing memories.",
                    "default": "general",
                },
            },
            "required": ["key", "value"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.TRUSTED

    async def execute(self, **kwargs: Any) -> ToolResult:
        key: str = kwargs["key"]
        value: str = kwargs["value"]
        category: str = kwargs.get("category", "general")

        try:
            await self._store.set(key, value, category=category)
            return ToolResult(
                success=True,
                output=f"Stored: {key} = {value}",
            )
        except Exception as e:
            log.exception("memory_set_error")
            return ToolResult(success=False, error=str(e))


class MemoryGetTool(BaseTool):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Retrieve a memory by key, or search memories by query."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Exact key to look up.",
                },
                "query": {
                    "type": "string",
                    "description": "Search term to find matching memories.",
                },
            },
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.TRUSTED

    async def execute(self, **kwargs: Any) -> ToolResult:
        key: str | None = kwargs.get("key")
        query: str | None = kwargs.get("query")

        if not key and not query:
            return ToolResult(
                success=False,
                error="Provide either 'key' or 'query' parameter.",
            )

        try:
            if key:
                result = await self._store.get(key)
                if result is None:
                    return ToolResult(
                        success=True,
                        output=f"No memory found for key: {key}",
                    )
                return ToolResult(
                    success=True,
                    output=f"[{result['category']}] {result['key']}: {result['value']}",
                    data=result,
                )
            else:
                assert query is not None
                results = await self._store.search(query)
                if not results:
                    return ToolResult(
                        success=True,
                        output=f"No memories found matching: {query}",
                    )
                lines = [
                    f"[{r['category']}] {r['key']}: {r['value']}"
                    for r in results
                ]
                return ToolResult(
                    success=True,
                    output="\n".join(lines),
                    data={"results": results},
                )
        except Exception as e:
            log.exception("memory_get_error")
            return ToolResult(success=False, error=str(e))


class MemoryDeleteTool(BaseTool):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "memory_delete"

    @property
    def description(self) -> str:
        return "Delete a memory entry by key."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key of the memory to delete.",
                },
            },
            "required": ["key"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.OPERATOR

    async def execute(self, **kwargs: Any) -> ToolResult:
        key: str = kwargs["key"]

        try:
            deleted = await self._store.delete(key)
            if deleted:
                return ToolResult(
                    success=True,
                    output=f"Deleted memory: {key}",
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"No memory found for key: {key}",
                )
        except Exception as e:
            log.exception("memory_delete_error")
            return ToolResult(success=False, error=str(e))
