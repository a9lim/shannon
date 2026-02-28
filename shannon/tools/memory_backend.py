"""MemoryBackend — client-side executor for Anthropic's memory_20250818 tool protocol.

Maps the virtual /memories/... path space to a local directory, executes file
operations requested by the LLM, and returns responses in the exact format that
the memory_20250818 tool specification documents.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path


class MemoryBackend:
    """Execute memory_20250818 tool commands against a local directory."""

    VIRTUAL_ROOT = "/memories"

    def __init__(self, base_dir: str) -> None:
        # The virtual /memories root maps to base_dir/memories/
        self._base = Path(base_dir).resolve()
        self._memories_root = self._base / "memories"

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve(self, virtual_path: str) -> Path | None:
        """Map a virtual /memories/... path to an absolute local path.

        The virtual root /memories maps to base_dir/memories/.
        Returns None if the resolved path escapes base_dir (traversal attempt).
        """
        # Decode URL-encoded characters before any checks
        decoded = urllib.parse.unquote(virtual_path)

        # Fast-reject any '..' in the decoded path
        if ".." in decoded:
            return None

        # Determine relative portion after /memories
        if decoded == self.VIRTUAL_ROOT or decoded == self.VIRTUAL_ROOT + "/":
            rel = ""
        elif decoded.startswith(self.VIRTUAL_ROOT + "/"):
            rel = decoded[len(self.VIRTUAL_ROOT) + 1:]
        else:
            return None

        # Build candidate and resolve symlinks / .. components
        candidate = (self._memories_root / rel).resolve()

        # Must stay within memories root (which is within base_dir)
        try:
            candidate.relative_to(self._base)
        except ValueError:
            return None

        return candidate

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(self, params: dict) -> str:
        """Dispatch a tool params dict to the appropriate handler."""
        command = params.get("command", "")
        if command == "view":
            return self._view(params)
        if command == "create":
            return self._create(params)
        if command == "str_replace":
            return self._str_replace(params)
        if command == "insert":
            return self._insert(params)
        if command == "delete":
            return self._delete(params)
        if command == "rename":
            return self._rename(params)
        return f"Error: unknown command '{command}'"

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _view(self, params: dict) -> str:
        path_str = params.get("path", "")
        local = self._resolve(path_str)

        if local is None or not local.exists():
            return f"The path {path_str} does not exist. Please provide a valid path."

        if local.is_dir():
            return self._view_directory(local, path_str)
        return self._view_file(local, path_str)

    def _view_directory(self, local: Path, virtual_path: str) -> str:
        lines = [
            f"Here're the files and directories up to 2 levels deep in {virtual_path},"
            " excluding hidden items and node_modules:"
        ]
        self._collect_tree(local, virtual_path, lines, depth=0, max_depth=2)
        return "\n".join(lines)

    def _collect_tree(
        self,
        local: Path,
        virtual_path: str,
        lines: list[str],
        depth: int,
        max_depth: int,
    ) -> None:
        if depth >= max_depth:
            return
        try:
            entries = sorted(local.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name == "node_modules":
                continue
            entry_virtual = virtual_path.rstrip("/") + "/" + entry.name
            if entry.is_dir():
                size_str = "-"
                lines.append(f"{size_str}\t{entry_virtual}/")
                self._collect_tree(entry, entry_virtual, lines, depth + 1, max_depth)
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{size}\t{entry_virtual}")

    def _view_file(self, local: Path, virtual_path: str) -> str:
        try:
            text = local.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error reading {virtual_path}: {exc}"
        file_lines = text.splitlines(keepends=True)
        result_lines = [f"Here's the content of {virtual_path} with line numbers:"]
        for i, line in enumerate(file_lines, start=1):
            # 6-char right-aligned line number, tab, then line content (strip trailing newline)
            result_lines.append(f"{i:>6}\t{line.rstrip(chr(10)+chr(13))}")
        return "\n".join(result_lines)

    def _create(self, params: dict) -> str:
        path_str = params.get("path", "")
        file_text = params.get("file_text", "")

        local = self._resolve(path_str)
        if local is None:
            return f"The path {path_str} does not exist. Please provide a valid path."

        if local.exists():
            return f"Error: File {path_str} already exists"

        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(file_text, encoding="utf-8")
        return f"File created successfully at: {path_str}"

    def _str_replace(self, params: dict) -> str:
        path_str = params.get("path", "")
        old_str = params.get("old_str", "")
        new_str = params.get("new_str", "")

        local = self._resolve(path_str)
        if local is None or not local.exists():
            return f"The path {path_str} does not exist. Please provide a valid path."

        try:
            content = local.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error reading {path_str}: {exc}"

        if old_str not in content:
            return f"Error: old_str not found in {path_str}"

        new_content = content.replace(old_str, new_str, 1)
        local.write_text(new_content, encoding="utf-8")
        return "The memory file has been edited."

    def _insert(self, params: dict) -> str:
        path_str = params.get("path", "")
        insert_line = params.get("insert_line", 0)
        new_str = params.get("new_str", "")

        local = self._resolve(path_str)
        if local is None or not local.exists():
            return f"The path {path_str} does not exist. Please provide a valid path."

        try:
            content = local.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error reading {path_str}: {exc}"

        lines = content.splitlines(keepends=True)
        # insert_line is 1-based: insert AFTER that line
        idx = int(insert_line)
        insert_text = new_str if new_str.endswith("\n") else new_str + "\n"
        lines.insert(idx, insert_text)
        local.write_text("".join(lines), encoding="utf-8")
        return "The memory file has been edited."

    def _delete(self, params: dict) -> str:
        path_str = params.get("path", "")
        local = self._resolve(path_str)

        if local is None or not local.exists():
            return f"The path {path_str} does not exist. Please provide a valid path."

        local.unlink()
        return f"Successfully deleted {path_str}"

    def _rename(self, params: dict) -> str:
        path_str = params.get("path", "")
        new_path_str = params.get("new_path", "")

        local = self._resolve(path_str)
        if local is None or not local.exists():
            return f"The path {path_str} does not exist. Please provide a valid path."

        new_local = self._resolve(new_path_str)
        if new_local is None:
            return f"The path {new_path_str} does not exist. Please provide a valid path."

        new_local.parent.mkdir(parents=True, exist_ok=True)
        local.rename(new_local)
        return f"Successfully renamed {path_str} to {new_path_str}"
