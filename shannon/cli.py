"""Thread-safe terminal I/O — output prints above the readline input line."""

from __future__ import annotations

import readline as _readline  # noqa: F401 — activates readline hooks for input()
import sys
import threading

_input_active = threading.Event()
_print_lock = threading.Lock()

PROMPT = "You> "


def safe_print(text: str) -> None:
    """Print *text* to stdout without clobbering the current input line.

    If ``input()`` is active (via :func:`safe_input`), the current line is
    cleared before printing and ``readline.redisplay()`` restores the prompt
    and partial input afterwards.  If no input is active, this is a plain
    ``print()``.
    """
    with _print_lock:
        if _input_active.is_set():
            # Wipe the prompt + whatever the user has typed so far
            buf = _readline.get_line_buffer()
            width = len(PROMPT) + len(buf)
            sys.stdout.write(f"\r{' ' * width}\r")

        sys.stdout.write(text + "\n")
        sys.stdout.flush()

        if _input_active.is_set():
            # Redraw the prompt and partial input
            _readline.redisplay()


def safe_input() -> str | None:
    """Readline-enabled ``input()`` that cooperates with :func:`safe_print`.

    Returns the stripped line, or ``None`` on EOF.
    """
    _input_active.set()
    try:
        return input(PROMPT)
    except EOFError:
        return None
    finally:
        _input_active.clear()
