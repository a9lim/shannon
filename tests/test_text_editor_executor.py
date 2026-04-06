# tests/test_text_editor_executor.py
"""Tests for TextEditorExecutor."""

import pytest
from pathlib import Path

from shannon.config import TextEditorConfig
from shannon.tools.text_editor_executor import TextEditorExecutor


@pytest.fixture
def executor():
    return TextEditorExecutor(TextEditorConfig())


# ---------------------------------------------------------------------------
# _view: file
# ---------------------------------------------------------------------------

def test_view_file(executor, tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line one\nline two\nline three\n")
    result = executor.execute({"command": "view", "path": str(f)})
    assert "Here's the content of" in result
    assert str(f) in result
    # line numbers right-aligned in 6 chars + tab
    assert "     1\tline one" in result
    assert "     2\tline two" in result
    assert "     3\tline three" in result


def test_view_file_with_view_range(executor, tmp_path):
    f = tmp_path / "range.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = executor.execute({"command": "view", "path": str(f), "view_range": [2, 4]})
    assert "     2\tb" in result
    assert "     4\td" in result
    # line 1 and 5 should not appear
    assert "     1\t" not in result
    assert "     5\t" not in result


# ---------------------------------------------------------------------------
# _view: directory
# ---------------------------------------------------------------------------

def test_view_directory(executor, tmp_path):
    (tmp_path / "alpha.txt").write_text("hello")
    (tmp_path / "beta.txt").write_text("world!!")
    result = executor.execute({"command": "view", "path": str(tmp_path)})
    assert "alpha.txt" in result
    assert "beta.txt" in result


# ---------------------------------------------------------------------------
# _view: nonexistent
# ---------------------------------------------------------------------------

def test_view_nonexistent(executor, tmp_path):
    missing = str(tmp_path / "no_such_file.txt")
    result = executor.execute({"command": "view", "path": missing})
    assert f"The path {missing} does not exist. Please provide a valid path." == result


# ---------------------------------------------------------------------------
# _create
# ---------------------------------------------------------------------------

def test_create_file(executor, tmp_path):
    target = tmp_path / "new_file.txt"
    result = executor.execute({
        "command": "create",
        "path": str(target),
        "file_text": "brand new content\n",
    })
    assert target.exists()
    assert target.read_text() == "brand new content\n"


def test_create_file_already_exists(executor, tmp_path):
    existing = tmp_path / "exists.txt"
    existing.write_text("original")
    result = executor.execute({
        "command": "create",
        "path": str(existing),
        "file_text": "should not overwrite",
    })
    assert result == f"Error: File {existing} already exists"
    assert existing.read_text() == "original"


# ---------------------------------------------------------------------------
# _str_replace
# ---------------------------------------------------------------------------

def test_str_replace_single_match(executor, tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    result = executor.execute({
        "command": "str_replace",
        "path": str(f),
        "old_str": "return 1",
        "new_str": "return 42",
    })
    assert f.read_text() == "def foo():\n    return 42\n"


def test_str_replace_no_match(executor, tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    old_str = "return 999"
    result = executor.execute({
        "command": "str_replace",
        "path": str(f),
        "old_str": old_str,
        "new_str": "return 0",
    })
    assert result == f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {f}."
    # file unchanged
    assert f.read_text() == "def foo():\n    return 1\n"


def test_str_replace_multiple_matches(executor, tmp_path):
    f = tmp_path / "dupe.txt"
    f.write_text("foo\nfoo\nbar\n")
    old_str = "foo"
    result = executor.execute({
        "command": "str_replace",
        "path": str(f),
        "old_str": old_str,
        "new_str": "baz",
    })
    # Must mention both line numbers (1 and 2)
    assert "No replacement was performed" in result
    assert "1" in result
    assert "2" in result
    assert f"`{old_str}`" in result
    # file unchanged
    assert f.read_text() == "foo\nfoo\nbar\n"


# ---------------------------------------------------------------------------
# _insert
# ---------------------------------------------------------------------------

def test_insert_at_line(executor, tmp_path):
    f = tmp_path / "insert.txt"
    f.write_text("line1\nline2\nline3\n")
    result = executor.execute({
        "command": "insert",
        "path": str(f),
        "insert_line": 2,
        "insert_text": "inserted\n",
    })
    lines = f.read_text().splitlines()
    assert lines[0] == "line1"
    assert lines[1] == "line2"
    assert lines[2] == "inserted"
    assert lines[3] == "line3"


def test_insert_at_line_zero(executor, tmp_path):
    """insert_line=0 inserts before all lines."""
    f = tmp_path / "insert0.txt"
    f.write_text("line1\nline2\n")
    executor.execute({
        "command": "insert",
        "path": str(f),
        "insert_line": 0,
        "insert_text": "first\n",
    })
    lines = f.read_text().splitlines()
    assert lines[0] == "first"
    assert lines[1] == "line1"


def test_str_replace_file_not_found(executor, tmp_path):
    missing = str(tmp_path / "ghost.py")
    result = executor.execute({
        "command": "str_replace",
        "path": missing,
        "old_str": "x",
        "new_str": "y",
    })
    assert result == f"The path {missing} does not exist. Please provide a valid path."


def test_insert_file_not_found(executor, tmp_path):
    missing = str(tmp_path / "ghost.py")
    result = executor.execute({
        "command": "insert",
        "path": missing,
        "insert_line": 1,
        "insert_text": "new line\n",
    })
    assert result == f"The path {missing} does not exist. Please provide a valid path."


def test_insert_adds_trailing_newline(executor, tmp_path):
    """Insert without trailing newline should not merge with next line."""
    f = tmp_path / "newline.txt"
    f.write_text("line1\nline2\nline3\n")
    executor.execute({
        "command": "insert",
        "path": str(f),
        "insert_line": 1,
        "insert_text": "inserted",  # no trailing newline
    })
    lines = f.read_text().splitlines()
    assert lines[1] == "inserted"
    assert lines[2] == "line2"


def test_view_range_single_element_returns_error(executor, tmp_path):
    """view_range with only one element should return an error."""
    f = tmp_path / "single.txt"
    f.write_text("a\nb\nc\n")
    result = executor.execute({"command": "view", "path": str(f), "view_range": [1]})
    assert "error" in result.lower()


def test_view_range_start_greater_than_end_returns_error(executor, tmp_path):
    """view_range where start > end should return an error."""
    f = tmp_path / "badrange.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = executor.execute({"command": "view", "path": str(f), "view_range": [5, 2]})
    assert "error" in result.lower() or "invalid" in result.lower()


def test_view_range_end_negative_one_reads_to_end(executor, tmp_path):
    """view_range with -1 as end should read to end of file."""
    f = tmp_path / "neg.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = executor.execute({"command": "view", "path": str(f), "view_range": [3, -1]})
    assert "     3\tc" in result
    assert "     4\td" in result
    assert "     5\te" in result
    assert "     1\t" not in result
    assert "     2\t" not in result


def test_view_range_start_zero_returns_error(executor, tmp_path):
    """view_range where start < 1 should return an error."""
    f = tmp_path / "zerostart.txt"
    f.write_text("a\nb\nc\n")
    result = executor.execute({"command": "view", "path": str(f), "view_range": [0, 5]})
    assert "error" in result.lower()


# ---------------------------------------------------------------------------
# _view: permission and encoding robustness
# ---------------------------------------------------------------------------


def test_view_directory_permission_error(executor, tmp_path):
    """Directory listing should handle PermissionError gracefully."""
    d = tmp_path / "noaccess"
    d.mkdir()
    d.chmod(0o000)
    result = executor.execute({"command": "view", "path": str(d)})
    d.chmod(0o755)  # restore for cleanup
    assert "permission" in result.lower() or "error" in result.lower()


def test_view_file_malformed_utf8(executor, tmp_path):
    """Malformed UTF-8 should be handled with replacement characters."""
    f = tmp_path / "bad.bin"
    f.write_bytes(b"good \xff bad \xfe end")
    result = executor.execute({"command": "view", "path": str(f)})
    assert "good" in result
    assert "end" in result


# ---------------------------------------------------------------------------
# _str_replace: permission and directory handling
# ---------------------------------------------------------------------------


def test_str_replace_on_directory_returns_error(executor, tmp_path):
    """str_replace on a directory should return an error."""
    d = tmp_path / "subdir"
    d.mkdir()
    result = executor.execute({
        "command": "str_replace",
        "path": str(d),
        "old_str": "x",
        "new_str": "y",
    })
    assert "does not exist" in result.lower() or "error" in result.lower()


def test_str_replace_permission_error(executor, tmp_path):
    """str_replace should handle PermissionError gracefully."""
    f = tmp_path / "readonly.txt"
    f.write_text("content")
    f.chmod(0o000)
    result = executor.execute({
        "command": "str_replace",
        "path": str(f),
        "old_str": "content",
        "new_str": "new",
    })
    f.chmod(0o644)  # restore for cleanup
    assert "permission" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# _insert: bounds validation and directory handling
# ---------------------------------------------------------------------------


def test_insert_negative_line_returns_error(executor, tmp_path):
    """Negative insert_line should be rejected."""
    f = tmp_path / "bounds.txt"
    f.write_text("line one\n")
    result = executor.execute({
        "command": "insert",
        "path": str(f),
        "insert_line": -1,
        "insert_text": "bad",
    })
    assert "Invalid" in result


def test_insert_beyond_file_length_returns_error(executor, tmp_path):
    """insert_line beyond file length should be rejected."""
    f = tmp_path / "bounds.txt"
    f.write_text("line one\nline two\n")
    result = executor.execute({
        "command": "insert",
        "path": str(f),
        "insert_line": 999,
        "insert_text": "bad",
    })
    assert "Invalid" in result
    assert "insert_line" in result


def test_insert_on_directory_returns_error(executor, tmp_path):
    """insert on a directory should return an error."""
    d = tmp_path / "subdir"
    d.mkdir()
    result = executor.execute({
        "command": "insert",
        "path": str(d),
        "insert_line": 0,
        "insert_text": "bad",
    })
    assert "does not exist" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# General error handling
# ---------------------------------------------------------------------------


def test_create_writes_utf8(tmp_path):
    """_create must write UTF-8 regardless of platform locale."""
    from shannon.config import TextEditorConfig
    from shannon.tools.text_editor_executor import TextEditorExecutor

    executor = TextEditorExecutor(TextEditorConfig())
    path = str(tmp_path / "unicode.txt")
    executor.execute({"command": "create", "path": path, "file_text": "caf\u00e9 \u00fc\u00e9"})
    raw = (tmp_path / "unicode.txt").read_bytes()
    assert raw.decode("utf-8") == "caf\u00e9 \u00fc\u00e9"


def test_unexpected_exception_returns_error_string(executor, tmp_path, monkeypatch):
    """Unexpected exceptions should be caught and returned as error strings."""
    import shannon.tools.text_editor_executor as te
    def bad_view(self, path, view_range):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(te.TextEditorExecutor, "_view", bad_view)
    result = executor.execute({"command": "view", "path": "/tmp/test"})
    assert "Error" in result
    assert "disk on fire" in result
