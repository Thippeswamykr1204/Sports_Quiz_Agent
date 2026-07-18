"""
Structured logging configuration.

Every log line is JSON-shaped and automatically carries the current
request_id (via a structlog processor reading core.request_context), so
logs are traceable end-to-end without manual plumbing.
"""

import logging
import sys

import structlog

from src.core.request_context import get_request_id


def _add_request_id(_logger, _method_name, event_dict):
    """structlog processor: injects the current request_id into every log line."""
    event_dict["request_id"] = get_request_id()
    return event_dict


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
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

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "sports_quiz_agent") -> structlog.stdlib.BoundLogger:
    """Returns a structlog logger bound to the given component name."""
    return structlog.get_logger(name)
