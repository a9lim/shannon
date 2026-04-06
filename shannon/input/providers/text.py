"""Async stdin text input provider."""

import asyncio

from shannon.cli import safe_input


class TextInputProvider:
    async def read_line(self) -> str | None:
        loop = asyncio.get_running_loop()
        line = await loop.run_in_executor(None, safe_input)
        if line is None:
            return None
        return line.strip()
