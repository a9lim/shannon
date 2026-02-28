"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import re
import sys

import structlog


_SENSITIVE_PATTERNS = [
    re.compile(r"(token|key|secret|password|authorization)[\"']?\s*[:=]\s*[\"']?[\w\-\.]+", re.IGNORECASE),
]


def _filter_sensitive(
    _logger: structlog.types.WrappedLogger,
    _method: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    for key, value in list(event_dict.items()):
        if not isinstance(value, str):
            continue
        for pattern in _SENSITIVE_PATTERNS:
            if pattern.search(value):
                event_dict[key] = pattern.sub(r"\1=***REDACTED***", value)
    return event_dict


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog with optional JSON output."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Warn if DEBUG is enabled — message content will be logged
    if numeric_level <= logging.DEBUG:
        print(
            "WARNING: DEBUG logging is enabled. Message content and sensitive "
            "data may appear in logs. Do not use in production.",
            file=sys.stderr,
        )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _filter_sensitive,
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # Quiet noisy libraries
    for name in ("discord", "httpx", "httpcore", "anthropic", "playwright"):
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
