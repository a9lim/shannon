"""Platform detection and path utilities."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def get_config_dir() -> Path:
    env = os.environ.get("SHANNON_CONFIG_DIR")
    if env:
        return Path(env)

    platform = get_platform()
    if platform == "windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "shannon"
    if platform == "macos":
        return Path.home() / "Library" / "Application Support" / "shannon"
    # Linux / XDG
    xdg = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(xdg) / "shannon"


def get_data_dir() -> Path:
    env = os.environ.get("SHANNON_DATA_DIR")
    if env:
        return Path(env)

    platform = get_platform()
    if platform == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "shannon"
    if platform == "macos":
        return Path.home() / "Library" / "Application Support" / "shannon"
    xdg = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(xdg) / "shannon"


def get_default_shell() -> str:
    if get_platform() == "windows":
        return "powershell"
    return os.environ.get("SHELL", "/bin/bash")


def normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()
