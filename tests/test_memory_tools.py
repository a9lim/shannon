"""Tests for memory tools."""

import pytest

from shannon.core.auth import PermissionLevel
from shannon.memory.store import MemoryStore
from shannon.tools.memory_tools import MemoryDeleteTool, MemoryGetTool, MemorySetTool


@pytest.fixture
async def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
def set_tool(store):
    return MemorySetTool(store)


@pytest.fixture
def get_tool(store):
    return MemoryGetTool(store)


@pytest.fixture
def delete_tool(store):
    return MemoryDeleteTool(store)


class TestMemorySetTool:
    def test_metadata(self, set_tool):
        assert set_tool.name == "memory_set"
        assert set_tool.required_permission == PermissionLevel.TRUSTED

    async def test_execute_sets_value(self, set_tool, store):
        result = await set_tool.execute(key="city", value="Portland")
        assert result.success is True
        assert "city" in result.output
        assert "Portland" in result.output

        entry = await store.get("city")
        assert entry is not None
        assert entry["value"] == "Portland"

    async def test_execute_with_category(self, set_tool, store):
        result = await set_tool.execute(
            key="lang", value="Python", category="dev"
        )
        assert result.success is True

        entry = await store.get("lang")
        assert entry is not None
        assert entry["category"] == "dev"


class TestMemoryGetTool:
    def test_metadata(self, get_tool):
        assert get_tool.name == "memory_get"
        assert get_tool.required_permission == PermissionLevel.TRUSTED

    async def test_execute_by_key(self, get_tool, store):
        await store.set("pet", "cat")
        result = await get_tool.execute(key="pet")
        assert result.success is True
        assert "cat" in result.output

    async def test_execute_nonexistent_key(self, get_tool):
        result = await get_tool.execute(key="nope")
        assert result.success is True
        assert "No memory found" in result.output

    async def test_execute_search(self, get_tool, store):
        await store.set("fav_color", "green")
        await store.set("fav_food", "pizza")
        result = await get_tool.execute(query="fav")
        assert result.success is True
        assert "green" in result.output
        assert "pizza" in result.output

    async def test_execute_no_params(self, get_tool):
        result = await get_tool.execute()
        assert result.success is False
        assert "Provide either" in result.error


class TestMemoryDeleteTool:
    def test_metadata(self, delete_tool):
        assert delete_tool.name == "memory_delete"
        assert delete_tool.required_permission == PermissionLevel.OPERATOR

    async def test_execute_success(self, delete_tool, store):
        await store.set("remove_me", "data")
        result = await delete_tool.execute(key="remove_me")
        assert result.success is True
        assert "Deleted" in result.output

        entry = await store.get("remove_me")
        assert entry is None

    async def test_execute_failure(self, delete_tool):
        result = await delete_tool.execute(key="not_there")
        assert result.success is False
        assert "No memory found" in result.error
