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


def test_view_file_with_view_range(backend, tmp_path):
    """view_range should return only the requested lines."""
    lines = "\n".join(f"line {i}" for i in range(1, 11))
    (tmp_path / "memories" / "long.md").write_text(lines)
    result = backend.execute({
        "command": "view",
        "path": "/memories/long.md",
        "view_range": [3, 5],
    })
    assert "line 3" in result
    assert "line 4" in result
    assert "line 5" in result
    assert "line 2" not in result
    assert "line 6" not in result
    # Line numbers should reflect original positions
    assert "     3\t" in result


def test_view_file_exceeding_line_limit(backend, tmp_path):
    """Files over 999,999 lines should be rejected."""
    # Write a file that claims many lines (we'll test the check, not actually write 1M lines)
    huge = "\n".join(["x"] * 1_000_000)
    (tmp_path / "memories" / "huge.md").write_text(huge)
    result = backend.execute({"command": "view", "path": "/memories/huge.md"})
    assert "999,999" in result or "999999" in result


def test_view_file_malformed_utf8(backend, tmp_path):
    """Malformed UTF-8 should be handled gracefully with replacement."""
    (tmp_path / "memories" / "bad.bin").write_bytes(b"good \xff bad \xfe end")
    result = backend.execute({"command": "view", "path": "/memories/bad.bin"})
    # Should not raise — replacement chars used
    assert "good" in result
    assert "end" in result


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


def test_str_replace_returns_context_snippet(backend, tmp_path):
    """Successful replacement should include a context snippet."""
    content = "line 1\nline 2\nold text\nline 4\nline 5\n"
    (tmp_path / "memories" / "notes.md").write_text(content)
    result = backend.execute({
        "command": "str_replace",
        "path": "/memories/notes.md",
        "old_str": "old text",
        "new_str": "new text",
    })
    assert "edited" in result.lower()
    assert "new text" in result


def test_str_replace_old_str_not_found(backend, tmp_path):
    (tmp_path / "memories" / "notes.md").write_text("hello world\n")
    result = backend.execute({
        "command": "str_replace",
        "path": "/memories/notes.md",
        "old_str": "nonexistent text",
        "new_str": "replacement",
    })
    assert "did not appear verbatim" in result


def test_str_replace_rejects_multiple_occurrences(backend, tmp_path):
    """When old_str appears multiple times, reject with line numbers."""
    content = "foo bar\nbaz\nfoo bar\n"
    (tmp_path / "memories" / "notes.md").write_text(content)
    result = backend.execute({
        "command": "str_replace",
        "path": "/memories/notes.md",
        "old_str": "foo bar",
        "new_str": "replaced",
    })
    assert "Multiple occurrences" in result
    assert "1" in result  # line 1
    assert "3" in result  # line 3
    # File should be unchanged
    assert (tmp_path / "memories" / "notes.md").read_text() == content


def test_str_replace_on_directory_returns_error(backend, tmp_path):
    (tmp_path / "memories" / "subdir").mkdir()
    result = backend.execute({
        "command": "str_replace",
        "path": "/memories/subdir",
        "old_str": "x",
        "new_str": "y",
    })
    assert "does not exist" in result.lower() or "error" in result.lower()


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


def test_insert_with_insert_text_key(backend, tmp_path):
    """Should accept insert_text as an alternative key name."""
    (tmp_path / "memories" / "notes.md").write_text("line one\nline three\n")
    result = backend.execute({
        "command": "insert",
        "path": "/memories/notes.md",
        "insert_line": 1,
        "insert_text": "line two",
    })
    content = (tmp_path / "memories" / "notes.md").read_text()
    assert "line two" in content


def test_insert_out_of_bounds_negative(backend, tmp_path):
    """Negative insert_line should be rejected."""
    (tmp_path / "memories" / "notes.md").write_text("line one\n")
    result = backend.execute({
        "command": "insert",
        "path": "/memories/notes.md",
        "insert_line": -1,
        "new_str": "bad",
    })
    assert "Invalid" in result


def test_insert_out_of_bounds_too_large(backend, tmp_path):
    """insert_line beyond file length should be rejected."""
    (tmp_path / "memories" / "notes.md").write_text("line one\n")
    result = backend.execute({
        "command": "insert",
        "path": "/memories/notes.md",
        "insert_line": 999,
        "new_str": "bad",
    })
    assert "Invalid" in result
    assert "insert_line" in result


def test_insert_on_directory_returns_error(backend, tmp_path):
    (tmp_path / "memories" / "subdir").mkdir()
    result = backend.execute({
        "command": "insert",
        "path": "/memories/subdir",
        "insert_line": 0,
        "new_str": "bad",
    })
    assert "does not exist" in result.lower() or "error" in result.lower()


# --- delete ---

def test_delete_file_success(backend, tmp_path):
    (tmp_path / "memories" / "todelete.md").write_text("bye")
    result = backend.execute({"command": "delete", "path": "/memories/todelete.md"})
    assert "Successfully deleted" in result
    assert not (tmp_path / "memories" / "todelete.md").exists()


def test_delete_file_not_found(backend):
    result = backend.execute({"command": "delete", "path": "/memories/ghost.md"})
    assert "does not exist" in result


def test_delete_directory_recursive(backend, tmp_path):
    """Deleting a directory should remove it and all contents."""
    subdir = tmp_path / "memories" / "subdir"
    subdir.mkdir()
    (subdir / "file.md").write_text("content")
    (subdir / "nested").mkdir()
    (subdir / "nested" / "deep.md").write_text("deep")

    result = backend.execute({"command": "delete", "path": "/memories/subdir"})
    assert "Successfully deleted" in result
    assert not subdir.exists()


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


def test_rename_rejects_existing_destination(backend, tmp_path):
    """Renaming to an existing path should be rejected."""
    (tmp_path / "memories" / "src.md").write_text("source")
    (tmp_path / "memories" / "dst.md").write_text("destination")
    result = backend.execute({
        "command": "rename",
        "path": "/memories/src.md",
        "new_path": "/memories/dst.md",
    })
    assert "already exists" in result
    # Both files should be unchanged
    assert (tmp_path / "memories" / "src.md").read_text() == "source"
    assert (tmp_path / "memories" / "dst.md").read_text() == "destination"


def test_rename_source_not_found(backend):
    result = backend.execute({
        "command": "rename",
        "path": "/memories/nonexistent.md",
        "new_path": "/memories/new.md",
    })
    assert "does not exist" in result


def test_rename_supports_old_path_key(backend, tmp_path):
    """Should accept old_path as an alternative key name."""
    (tmp_path / "memories" / "old.md").write_text("content")
    result = backend.execute({
        "command": "rename",
        "old_path": "/memories/old.md",
        "new_path": "/memories/new.md",
    })
    assert "Successfully renamed" in result
    assert (tmp_path / "memories" / "new.md").exists()


# --- unknown command ---

def test_unknown_command(backend):
    result = backend.execute({"command": "foobar"})
    assert "Unknown command" in result


# --- error handling ---

def test_exception_in_command_returns_error_string(backend, tmp_path, monkeypatch):
    """Unexpected exceptions should be caught and returned as error strings."""
    import shannon.tools.memory_backend as mb
    original_resolve = mb.MemoryBackend._resolve
    def bad_resolve(self, path):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(mb.MemoryBackend, "_resolve", bad_resolve)
    result = backend.execute({"command": "view", "path": "/memories"})
    assert "Error" in result
    assert "disk on fire" in result


# --- path traversal ---

def test_path_traversal_blocked(backend):
    result = backend.execute({"command": "view", "path": "/memories/../secret"})
    assert "traversal" in result.lower() or "does not exist" in result


def test_path_traversal_absolute_escape_blocked(backend, tmp_path):
    # Attempt to escape base_dir entirely
    result = backend.execute({"command": "view", "path": "/memories/../../etc/passwd"})
    assert "traversal" in result.lower() or "does not exist" in result


def test_path_traversal_url_encoded_blocked(backend):
    """URL-encoded '..' traversal should be rejected."""
    result = backend.execute({"command": "view", "path": "/memories/%2e%2e/secret"})
    assert "traversal" in result.lower() or "does not exist" in result


def test_path_traversal_double_url_encoded_blocked(backend):
    """Double URL-encoded traversal should be rejected."""
    result = backend.execute({"command": "view", "path": "/memories/%252e%252e/secret"})
    assert "does not exist" in result or "traversal" in result.lower()


def test_path_traversal_mixed_encoding_blocked(backend):
    """Mixed encoded/literal '..' should be rejected."""
    result = backend.execute({"command": "view", "path": "/memories/..%2f..%2fetc/passwd"})
    assert "traversal" in result.lower() or "does not exist" in result


def test_resolve_rejects_symlink_escaping_memories_root(tmp_path):
    """A symlink inside memories/ pointing outside memories/ (but inside base_dir) must be rejected."""
    memories_dir = tmp_path / "memories"
    memories_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret data")
    link = memories_dir / "escape"
    link.symlink_to(secret)

    backend = MemoryBackend(base_dir=str(tmp_path))
    result = backend.execute({"command": "view", "path": "/memories/escape"})
    assert "does not exist" in result or "escapes" in result.lower()
