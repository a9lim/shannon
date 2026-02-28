# shannon/tools/text_editor_executor.py
"""Execution backend for Anthropic's text_editor_20250728 tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shannon.config import TextEditorConfig


class TextEditorExecutor:
    """Execute text-editor tool commands dispatched from the LLM."""

    def __init__(self, config: TextEditorConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(self, params: dict[str, Any]) -> str:
        command = params.get("command")
        path = params.get("path", "")

        if command == "view":
            return self._view(path, params.get("view_range"))
        elif command == "create":
            return self._create(path, params.get("file_text", ""))
        elif command == "str_replace":
            return self._str_replace(path, params.get("old_str", ""), params.get("new_str", ""))
        elif command == "insert":
            return self._insert(path, params.get("insert_line", 0), params.get("insert_text", ""))
        else:
            return f"Unknown command: {command}"

    # ------------------------------------------------------------------
    # _view
    # ------------------------------------------------------------------

    def _view(self, path: str, view_range: list[int] | None) -> str:
        p = Path(path)
        if not p.exists():
            return f"The path {path} does not exist. Please provide a valid path."

        if p.is_dir():
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
            lines = []
            for entry in entries:
                if entry.is_file():
                    size = entry.stat().st_size
                    lines.append(f"{entry.name}  ({size} bytes)")
                else:
                    lines.append(f"{entry.name}/")
            return f"Directory listing of {path}:\n" + "\n".join(lines)

        content = p.read_text(errors="replace")
        all_lines = content.splitlines(keepends=True)

        if view_range is not None:
            start, end = view_range[0], view_range[1]
            # 1-indexed, inclusive
            selected = all_lines[start - 1:end]
            numbered = "".join(
                f"{i:>6}\t{line}" for i, line in enumerate(selected, start=start)
            )
        else:
            numbered = "".join(
                f"{i:>6}\t{line}" for i, line in enumerate(all_lines, start=1)
            )

        return f"Here's the content of {path} with line numbers:\n{numbered}"

    # ------------------------------------------------------------------
    # _create
    # ------------------------------------------------------------------

    def _create(self, path: str, file_text: str) -> str:
        p = Path(path)
        if p.exists():
            return f"Error: File {path} already exists"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(file_text)
        return f"File created successfully at {path}"

    # ------------------------------------------------------------------
    # _str_replace
    # ------------------------------------------------------------------

    def _str_replace(self, path: str, old_str: str, new_str: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"The path {path} does not exist. Please provide a valid path."

        content = p.read_text(errors="replace")

        # Count occurrences and track which lines they start on
        occurrences: list[int] = []
        search_start = 0
        while True:
            idx = content.find(old_str, search_start)
            if idx == -1:
                break
            line_number = content[:idx].count("\n") + 1
            occurrences.append(line_number)
            search_start = idx + len(old_str)

        if len(occurrences) == 0:
            return (
                f"No replacement was performed, old_str `{old_str}` "
                f"did not appear verbatim in {path}."
            )

        if len(occurrences) > 1:
            line_numbers = ", ".join(str(n) for n in occurrences)
            return (
                f"No replacement was performed. Multiple occurrences of old_str "
                f"`{old_str}` in lines: {line_numbers}. Please ensure it is unique"
            )

        new_content = content.replace(old_str, new_str, 1)
        p.write_text(new_content)
        return f"Replacement performed successfully in {path}"

    # ------------------------------------------------------------------
    # _insert
    # ------------------------------------------------------------------

    def _insert(self, path: str, insert_line: int, insert_text: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"The path {path} does not exist. Please provide a valid path."

        content = p.read_text(errors="replace")
        lines = content.splitlines(keepends=True)

        # insert_line is 1-indexed; insert after that line.
        # insert_line=0 means insert before everything.
        lines.insert(insert_line, insert_text)
        p.write_text("".join(lines))
        return f"Text inserted at line {insert_line} in {path}"
