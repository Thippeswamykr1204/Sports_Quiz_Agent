"""
Rate limiting hook point.

RateLimiter is a Protocol so quiz_service.py can accept one without
depending on a specific backend. InMemoryRateLimiter is a real, working
sliding-window implementation suitable for a single-process Streamlit
deployment; a multi-instance deployment would swap in a Redis-backed
implementation against this same interface (Future Enhancement).

This is deliberately NOT wired into QuizService by default (rate_limiter
defaults to None there) — a single-user local Streamlit app doesn't need
enforcement day-one, but the architecture is ready for it the moment a
public-facing deployment needs it, without touching orchestration logic.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Protocol

from src.core.exceptions import RateLimitExceededError
from src.core.logging import get_logger

logger = get_logger("rate_limiter")


class RateLimiter(Protocol):
    """Interface for rate-limiting requests by an arbitrary identity key."""

    def check(self, identity: str) -> None:
        """Raises RateLimitExceededError if identity has exceeded its allowance."""
        ...


class InMemoryRateLimiter:
    """
    Sliding-window rate limiter, in-process memory only.

    Not suitable for multi-process/multi-instance deployments (each
    process has its own window) — fine for a single Streamlit process.
    Guarded by a lock since build_service() is a st.cache_resource
    singleton shared across every session's thread, so check() can be
    called concurrently.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, identity: str) -> None:
        with self._lock:
            now = time.monotonic()
            window = self._requests[identity]

            while window and now - window[0] > self._window_seconds:
                window.popleft()

            if len(window) >= self._max_requests:
                oldest = window[0]
                retry_after = self._window_seconds - (now - oldest)
                logger.warning("rate_limit_exceeded", identity=identity, retry_after=retry_after)
                raise RateLimitExceededError(identity, retry_after)

            window.append(now)