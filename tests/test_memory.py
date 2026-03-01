"""Tests for the persistent memory store."""

import pytest

from shannon.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    s = MemoryStore(tmp_path / "memory.db")
    await s.start()
    yield s
    await s.stop()


class TestMemoryStore:
    async def test_set_and_get(self, store):
        await store.set("name", "Shannon")
        result = await store.get("name")
        assert result is not None
        assert result["key"] == "name"
        assert result["value"] == "Shannon"
        assert result["category"] == "general"
        assert result["created_at"]
        assert result["updated_at"]
        assert result["source"] == ""

    async def test_get_nonexistent(self, store):
        result = await store.get("nonexistent")
        assert result is None

    async def test_update_existing_key(self, store):
        await store.set("color", "blue")
        result1 = await store.get("color")
        assert result1 is not None
        created_at = result1["created_at"]

        await store.set("color", "red")
        result2 = await store.get("color")
        assert result2 is not None
        assert result2["value"] == "red"
        # created_at should stay the same (ON CONFLICT keeps original)
        # updated_at should be different
        assert result2["updated_at"] >= created_at

    async def test_delete_existing(self, store):
        await store.set("temp", "data")
        deleted = await store.delete("temp")
        assert deleted is True
        result = await store.get("temp")
        assert result is None

    async def test_delete_nonexistent(self, store):
        deleted = await store.delete("ghost")
        assert deleted is False

    async def test_search_by_key(self, store):
        await store.set("user_name", "Alice")
        await store.set("user_email", "alice@example.com")
        await store.set("server_ip", "10.0.0.1")

        results = await store.search("user")
        assert len(results) == 2
        keys = {r["key"] for r in results}
        assert keys == {"user_name", "user_email"}

    async def test_search_by_value(self, store):
        await store.set("greeting", "hello world")
        await store.set("farewell", "goodbye world")
        await store.set("code", "print('hi')")

        results = await store.search("world")
        assert len(results) == 2
        keys = {r["key"] for r in results}
        assert keys == {"greeting", "farewell"}

    async def test_search_no_results(self, store):
        await store.set("a", "b")
        results = await store.search("zzz_no_match")
        assert results == []

    async def test_list_category(self, store):
        await store.set("k1", "v1", category="prefs")
        await store.set("k2", "v2", category="prefs")
        await store.set("k3", "v3", category="facts")

        prefs = await store.list_category("prefs")
        assert len(prefs) == 2
        keys = {r["key"] for r in prefs}
        assert keys == {"k1", "k2"}

    async def test_list_empty_category(self, store):
        results = await store.list_category("empty_cat")
        assert results == []

    async def test_export_context_empty(self, store):
        text = await store.export_context()
        assert text == ""

    async def test_export_context_with_memories(self, store):
        await store.set("name", "Shannon", category="identity")
        await store.set("color", "blue", category="prefs")

        text = await store.export_context()
        assert "[identity] name: Shannon" in text
        assert "[prefs] color: blue" in text

    async def test_export_context_truncation(self, store):
        # max_tokens=1 means max_chars=4, should truncate aggressively
        for i in range(20):
            await store.set(f"key_{i:02d}", f"value_{i:02d}" * 10, category="bulk")

        text = await store.export_context(max_tokens=1)
        # With only 4 chars allowed, we should get very little or nothing
        assert len(text) <= 4

    async def test_clear(self, store):
        await store.set("a", "1")
        await store.set("b", "2")
        await store.set("c", "3")

        count = await store.clear()
        assert count == 3

        result = await store.get("a")
        assert result is None

    async def test_set_with_category_and_source(self, store):
        await store.set("fact", "sky is blue", category="science", source="user")
        result = await store.get("fact")
        assert result is not None
        assert result["category"] == "science"
        assert result["source"] == "user"
