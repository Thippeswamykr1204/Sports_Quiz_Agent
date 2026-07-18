"""
Request-scoped context.

Generates a request_id per quiz-generation call and makes it available to
every layer via a ContextVar, so log lines across retrieval, generation,
and caching automatically correlate to the same request without threading
an extra parameter through every function signature.
"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_request_id_var: ContextVar[str] = ContextVar("request_id", default="unbound")


def get_request_id() -> str:
    """Returns the request_id for the current context, or 'unbound' if none set."""
    return _request_id_var.get()


def new_request_id() -> str:
    """Generates a short, human-scannable request ID (not a full UUID string)."""
    return uuid.uuid4().hex[:12]


@contextmanager
def request_scope(request_id: str | None = None) -> Iterator[str]:
    """
    Context manager that binds a request_id for the duration of the block.

    Usage:
        with request_scope() as rid:
            logger.info("starting quiz generation", request_id=rid)
            ...
    """
    rid = request_id or new_request_id()
    token = _request_id_var.set(rid)
    try:
        yield rid
    finally:
        _request_id_var.reset(token)
