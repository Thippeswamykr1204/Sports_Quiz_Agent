"""
Structured logging configuration.

Every log line is JSON-shaped and automatically carries the current
request_id (via a structlog processor reading core.request_context), so
logs are traceable end-to-end without manual plumbing.

Optionally tees output to a log file (in addition to stdout) so the
Settings page's "Export Logs" can offer a real file to download instead
of a fabricated one - when no log_file_path is configured, Export Logs
must say so honestly rather than inventing content.
"""

import logging
import sys
from pathlib import Path

import structlog

from src.core.request_context import get_request_id


class _TeeWriter:
    """Writes to multiple file-like streams - lets structlog's PrintLoggerFactory hit both stdout and a file."""

    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, data: str) -> None:
        for stream in self._streams:
            stream.write(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _add_request_id(_logger, _method_name, event_dict):
    """structlog processor: injects the current request_id into every log line."""
    event_dict["request_id"] = get_request_id()
    return event_dict


def configure_logging(log_level: str = "INFO", json_output: bool = True, log_file_path: Path | None = None) -> None:
    """
    Configures stdlib logging + structlog once per process.

    Call this exactly once at application startup (app.py). Safe to call
    multiple times; structlog reconfiguration is idempotent enough for our
    use case since we always pass the same processor chain.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
    )

    output_stream = sys.stdout
    if log_file_path is not None:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handle = open(log_file_path, "a", encoding="utf-8")
        output_stream = _TeeWriter(sys.stdout, file_handle)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output_stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "sports_quiz_agent") -> structlog.stdlib.BoundLogger:
    """Returns a structlog logger bound to the given component name."""
    return structlog.get_logger(name)