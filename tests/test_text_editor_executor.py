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
