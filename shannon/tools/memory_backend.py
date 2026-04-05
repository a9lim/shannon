"""MemoryBackend — client-side executor for Anthropic's memory_20250818 tool protocol.

Maps the virtual /memories/... path space to a local directory, executes file
operations requested by the LLM, and returns responses in the exact format that
the memory_20250818 tool specification documents.
"""

from __future__ import annotations

import logging
import shutil
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)


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

    def _resolve(self, virtual_path: str) -> Path:
        """Map a virtual /memories/... path to an absolute local path.

        The virtual root /memories maps to base_dir/memories/.
        Raises ValueError if the resolved path escapes the memories root
        (traversal attempt).
        """
        # Decode URL-encoded characters before any checks
        decoded = urllib.parse.unquote(virtual_path)

        # Fast-reject any '..' in the decoded path
        if ".." in decoded:
            raise ValueError(f"Path traversal detected: {virtual_path}")

        # Determine relative portion after /memories
        if decoded == self.VIRTUAL_ROOT or decoded == self.VIRTUAL_ROOT + "/":
            rel = ""
        elif decoded.startswith(self.VIRTUAL_ROOT + "/"):
            rel = decoded[len(self.VIRTUAL_ROOT) + 1:]
        else:
            raise ValueError(
                f"The path {virtual_path} does not exist. Please provide a valid path."
            )

        # Build candidate and resolve symlinks / .. components
        candidate = (self._memories_root / rel).resolve()

        # Must stay within memories root (which is within base_dir)
        try:
            candidate.relative_to(self._memories_root)
        except ValueError:
            raise ValueError(
                f"Path escapes memory directory: {virtual_path}"
            )

        return candidate

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(self, params: dict) -> str:
        """Dispatch a tool params dict to the appropriate handler."""
        command = params.get("command", "")
        try:
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
            return f"Error: Unknown command '{command}'"
        except ValueError as e:
            return str(e)
        except Exception as e:
            logger.exception("Memory command '%s' failed.", command)
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _view(self, params: dict) -> str:
        path_str = params.get("path", "")
        local = self._resolve(path_str)

        if not local.exists():
            return f"The path {path_str} does not exist. Please provide a valid path."

        if local.is_dir():
            return self._view_directory(local, path_str)
        return self._view_file(local, path_str, params.get("view_range"))

    def _view_directory(self, local: Path, virtual_path: str) -> str:
        header = (
            f"Here're the files and directories up to 2 levels deep in {virtual_path},"
            " excluding hidden items and node_modules:"
        )
        lines: list[str] = [header]
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
                lines.append(f"-\t{entry_virtual}/")
                self._collect_tree(entry, entry_virtual, lines, depth + 1, max_depth)
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{size}\t{entry_virtual}")

    def _view_file(self, local: Path, virtual_path: str, view_range: list | None = None) -> str:
        try:
            text = local.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied reading {virtual_path}"
        except OSError as exc:
            return f"Error reading {virtual_path}: {exc}"

        file_lines = text.splitlines()

        if len(file_lines) > 999_999:
            return f"File {virtual_path} exceeds maximum line limit of 999,999 lines."

        # Support view_range for partial file viewing
        if view_range and len(view_range) == 2:
            start, end = int(view_range[0]), int(view_range[1])
            selected = file_lines[start - 1 : end]
            start_num = start
        else:
            selected = file_lines
            start_num = 1

        result_lines = [f"Here's the content of {virtual_path} with line numbers:"]
        for i, line in enumerate(selected, start=start_num):
            result_lines.append(f"{i:>6}\t{line}")
        return "\n".join(result_lines)

    def _create(self, params: dict) -> str:
        path_str = params.get("path", "")
        file_text = params.get("file_text", "")

        local = self._resolve(path_str)

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
        if not local.exists() or local.is_dir():
            return f"Error: The path {path_str} does not exist. Please provide a valid path."

        try:
            content = local.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied reading {path_str}"
        except OSError as exc:
            return f"Error reading {path_str}: {exc}"

        # Check occurrences — reject ambiguous replacements
        count = content.count(old_str)
        if count == 0:
            return (
                f"No replacement was performed, old_str `{old_str}` "
                f"did not appear verbatim in {path_str}."
            )
        if count > 1:
            lines = content.splitlines()
            line_nums = [i + 1 for i, line in enumerate(lines) if old_str in line]
            return (
                f"No replacement was performed. Multiple occurrences of old_str "
                f"`{old_str}` in lines: {line_nums}. Please ensure it is unique"
            )

        new_content = content.replace(old_str, new_str, 1)
        local.write_text(new_content, encoding="utf-8")

        # Show context snippet around the replacement
        new_lines = new_content.splitlines()
        for i, line in enumerate(new_lines):
            if new_str in line:
                start = max(0, i - 2)
                end = min(len(new_lines), i + 3)
                snippet = "\n".join(
                    f"{j + 1:>6}\t{new_lines[j]}" for j in range(start, end)
                )
                return f"The memory file has been edited.\n{snippet}"

        return "The memory file has been edited."

    def _insert(self, params: dict) -> str:
        path_str = params.get("path", "")
        insert_line = params.get("insert_line", 0)
        new_str = params.get("new_str", params.get("insert_text", ""))

        local = self._resolve(path_str)
        if not local.exists() or local.is_dir():
            return f"Error: The path {path_str} does not exist"

        try:
            content = local.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied reading {path_str}"
        except OSError as exc:
            return f"Error reading {path_str}: {exc}"

        lines = content.splitlines()
        n_lines = len(lines)
        idx = int(insert_line)

        # Validate insertion bounds
        if idx < 0 or idx > n_lines:
            return (
                f"Error: Invalid `insert_line` parameter: {insert_line}. "
                f"It should be within the range of lines of the file: [0, {n_lines}]"
            )

        new_lines = new_str.splitlines()
        lines[idx:idx] = new_lines
        local.write_text("\n".join(lines), encoding="utf-8")
        return f"The file {path_str} has been edited."

    def _delete(self, params: dict) -> str:
        path_str = params.get("path", "")
        local = self._resolve(path_str)

        if not local.exists():
            return f"Error: The path {path_str} does not exist"

        if local.is_dir():
            shutil.rmtree(local)
        else:
            local.unlink()
        return f"Successfully deleted {path_str}"

    def _rename(self, params: dict) -> str:
        # Support both "path"/"new_path" and "old_path"/"new_path" key names
        path_str = params.get("path", params.get("old_path", ""))
        new_path_str = params.get("new_path", "")

        local = self._resolve(path_str)
        if not local.exists():
            return f"Error: The path {path_str} does not exist"

        new_local = self._resolve(new_path_str)
        if new_local.exists():
            return f"Error: The destination {new_path_str} already exists"

        new_local.parent.mkdir(parents=True, exist_ok=True)
        local.rename(new_local)
        return f"Successfully renamed {path_str} to {new_path_str}"
