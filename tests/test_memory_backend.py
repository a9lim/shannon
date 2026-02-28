"""Tests for MemoryBackend — Anthropic memory_20250818 protocol storage."""

import pytest
from pathlib import Path

from shannon.tools.memory_backend import MemoryBackend


@pytest.fixture
def backend(tmp_path):
    memories_dir = tmp_path / "memories"
    memories_dir.mkdir()
    return MemoryBackend(base_dir=str(tmp_path))


# --- view ---

def test_view_empty_directory(backend, tmp_path):
    result = backend.execute({"command": "view", "path": "/memories"})
    assert "/memories" in result
    # no files yet — listing should succeed and show the directory
    assert "Here're the files" in result


def test_view_directory_lists_files(backend, tmp_path):
    (tmp_path / "memories" / "notes.md").write_text("hello")
    result = backend.execute({"command": "view", "path": "/memories"})
    assert "notes.md" in result


def test_view_file_shows_content_with_line_numbers(backend, tmp_path):
    (tmp_path / "memories" / "notes.md").write_text("line one\nline two\n")
    result = backend.execute({"command": "view", "path": "/memories/notes.md"})
    assert "line one" in result
    assert "line two" in result
    # line numbers should be right-aligned in 6 chars
    assert "     1\t" in result
    assert "     2\t" in result


def test_view_file_not_found(backend):
    result = backend.execute({"command": "view", "path": "/memories/missing.md"})
    assert "does not exist" in result


# --- create ---

def test_create_file_success(backend, tmp_path):
    result = backend.execute({
        "command": "create",
        "path": "/memories/new.md",
        "file_text": "# New file\n",
    })
    assert "File created successfully" in result
    assert (tmp_path / "memories" / "new.md").exists()
    assert (tmp_path / "memories" / "new.md").read_text() == "# New file\n"


def test_create_file_already_exists(backend, tmp_path):
    (tmp_path / "memories" / "existing.md").write_text("already here")
    result = backend.execute({
        "command": "create",
        "path": "/memories/existing.md",
        "file_text": "new content",
    })
    assert "already exists" in result
    # original content unchanged
    assert (tmp_path / "memories" / "existing.md").read_text() == "already here"


# --- str_replace ---

def test_str_replace_success(backend, tmp_path):
    (tmp_path / "memories" / "notes.md").write_text("hello world\n")
    result = backend.execute({
        "command": "str_replace",
        "path": "/memories/notes.md",
        "old_str": "hello world",
        "new_str": "goodbye world",
    })
    assert "edited" in result.lower()
    assert (tmp_path / "memories" / "notes.md").read_text() == "goodbye world\n"


def test_str_replace_old_str_not_found(backend, tmp_path):
    (tmp_path / "memories" / "notes.md").write_text("hello world\n")
    result = backend.execute({
        "command": "str_replace",
        "path": "/memories/notes.md",
        "old_str": "nonexistent text",
        "new_str": "replacement",
    })
    assert "does not exist" in result or "not found" in result.lower() or "error" in result.lower()


# --- insert ---

def test_insert_line(backend, tmp_path):
    (tmp_path / "memories" / "notes.md").write_text("line one\nline three\n")
    result = backend.execute({
        "command": "insert",
        "path": "/memories/notes.md",
        "insert_line": 1,
        "new_str": "line two",
    })
    content = (tmp_path / "memories" / "notes.md").read_text()
    lines = content.splitlines()
    assert lines[0] == "line one"
    assert lines[1] == "line two"
    assert lines[2] == "line three"


# --- delete ---

def test_delete_file_success(backend, tmp_path):
    (tmp_path / "memories" / "todelete.md").write_text("bye")
    result = backend.execute({"command": "delete", "path": "/memories/todelete.md"})
    assert "Successfully deleted" in result
    assert not (tmp_path / "memories" / "todelete.md").exists()


def test_delete_file_not_found(backend):
    result = backend.execute({"command": "delete", "path": "/memories/ghost.md"})
    assert "does not exist" in result


# --- rename ---

def test_rename_file_success(backend, tmp_path):
    (tmp_path / "memories" / "old.md").write_text("content")
    result = backend.execute({
        "command": "rename",
        "path": "/memories/old.md",
        "new_path": "/memories/new.md",
    })
    assert "Successfully renamed" in result
    assert not (tmp_path / "memories" / "old.md").exists()
    assert (tmp_path / "memories" / "new.md").exists()


# --- path traversal ---

def test_path_traversal_blocked(backend):
    result = backend.execute({"command": "view", "path": "/memories/../secret"})
    assert "does not exist" in result or "invalid" in result.lower() or "path" in result.lower()


def test_path_traversal_absolute_escape_blocked(backend, tmp_path):
    # Attempt to escape base_dir entirely
    result = backend.execute({"command": "view", "path": "/memories/../../etc/passwd"})
    assert "does not exist" in result or "invalid" in result.lower() or "path" in result.lower()


def test_path_traversal_url_encoded_blocked(backend):
    """URL-encoded '..' traversal should be rejected."""
    result = backend.execute({"command": "view", "path": "/memories/%2e%2e/secret"})
    assert "does not exist" in result or "traversal" in result.lower()


def test_path_traversal_double_url_encoded_blocked(backend):
    """Double URL-encoded traversal should be rejected."""
    result = backend.execute({"command": "view", "path": "/memories/%252e%252e/secret"})
    assert "does not exist" in result or "traversal" in result.lower()


def test_path_traversal_mixed_encoding_blocked(backend):
    """Mixed encoded/literal '..' should be rejected."""
    result = backend.execute({"command": "view", "path": "/memories/..%2f..%2fetc/passwd"})
    assert "does not exist" in result or "traversal" in result.lower()
