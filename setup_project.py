#!/usr/bin/env python3
"""
Shannon Project Setup Script

This script creates all necessary project files for the Shannon assistant.
Run this after cloning the repository to set up the complete project structure.
"""

import os
from pathlib import Path

# Project root
ROOT = Path(__file__).parent

# File definitions (relative paths)
FILES = {
    # Configuration
    ".gitignore": """# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class

# Distribution / packaging
.Python
build/
dist/
*.egg-info/

# pytest
.pytest_cache/
.coverage
htmlcov/

# Environments
.env
.venv
venv/

# Project-specific
data/
logs/
*.db
.claude/
""",

    ".dockerignore": """.git
__pycache__
.pytest_cache
.coverage
data/
logs/
.env
.env.local
.DS_Store
venv/
.venv/
""",

    ".env.example": """# Shannon Environment Variables
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
DISCORD_BOT_TOKEN=your_discord_bot_token_here
SIGNAL_PHONE_NUMBER=+1234567890
""",

    # Create core module
    "shannon/__init__.py": """\"\"\"Shannon - LLM-Powered Autonomous Assistant\"\"\"
__version__ = "0.1.0"
""",

    "shannon/utils/__init__.py": """\"\"\"Utility modules for Shannon.\"\"\"

from .logging import get_logger, setup_logging
from .sanitize import sanitize_shell_input, sanitize_file_path, sanitize_prompt_input, truncate_for_logging

__all__ = [
    "get_logger",
    "setup_logging",
    "sanitize_shell_input",
    "sanitize_file_path",
    "sanitize_prompt_input",
    "truncate_for_logging",
]
""",

    "shannon/core/__init__.py": """\"\"\"Core modules for Shannon.\"\"\"

from .auth import AuthManager, PermissionLevel
from .brain import Brain
from .memory import MemoryManager
from .chunker import chunk_message, send_chunks

__all__ = [
    "AuthManager",
    "PermissionLevel",
    "Brain",
    "MemoryManager",
    "chunk_message",
    "send_chunks",
]
""",

    "shannon/interfaces/__init__.py": """\"\"\"Message interfaces for Shannon.\"\"\"

from .base import MessageInterface, IncomingMessage

__all__ = ["MessageInterface", "IncomingMessage"]
""",

    "shannon/tools/__init__.py": """\"\"\"Tool modules for Shannon.\"\"\"

from .shell import run_shell
from .browser import BrowserTool
from .file_manager import FileManager
from .interactive import InteractiveSession
from .claude_code import run_claude_code

__all__ = [
    "run_shell",
    "BrowserTool",
    "FileManager",
    "InteractiveSession",
    "run_claude_code",
]
""",

    "shannon/scheduler/__init__.py": """\"\"\"Scheduler modules for Shannon.\"\"\"

from .task_queue import TaskQueue, ScheduledTask
from .cron_manager import CronManager
from .heartbeat import Heartbeat

__all__ = [
    "TaskQueue",
    "ScheduledTask",
    "CronManager",
    "Heartbeat",
]
""",

    "shannon/tests/__init__.py": """\"\"\"Tests for Shannon.\"\"\"
""",

    "Dockerfile": """FROM python:3.11-slim

RUN apt-get update && apt-get install -y chromium-browser cron curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install chromium

COPY . .
RUN mkdir -p data logs

EXPOSE 8000
ENTRYPOINT ["python", "shannon.py"]
""",
}


def create_files():
    """Create all project files."""
    created = 0
    skipped = 0

    for file_path, content in FILES.items():
        full_path = ROOT / file_path

        if full_path.exists():
            print(f"⊘ Skipped (exists): {file_path}")
            skipped += 1
            continue

        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(full_path, 'w') as f:
            f.write(content)

        print(f"✓ Created: {file_path}")
        created += 1

    print(f"\n✅ Created {created} files, skipped {skipped} existing files")
    print("\n⚠️  Note: Full implementation files need to be created manually or downloaded from the repository.")
    print("\nTo complete setup:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Create .env file with your API keys")
    print("3. Run tests: pytest tests/ -v")
    print("4. Start Shannon: python shannon.py")


if __name__ == "__main__":
    create_files()
