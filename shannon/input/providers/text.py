"""Async stdin text input provider."""

import asyncio
import sys


class TextInputProvider:
    async def read_line(self) -> str | None:
        loop = asyncio.get_running_loop()
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return None
        return line.strip()
