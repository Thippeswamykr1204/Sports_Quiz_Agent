"""Unit tests for the in-memory sliding-window rate limiter."""

import time

import pytest

from src.core.exceptions import RateLimitExceededError
from src.core.rate_limiter import InMemoryRateLimiter


def test_allows_requests_under_the_limit():
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=10)

    limiter.check("user_a")
    limiter.check("user_a")
    limiter.check("user_a")  # 3rd request, still within limit


def test_blocks_requests_over_the_limit():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=10)

    limiter.check("user_a")
    limiter.check("user_a")

    with pytest.raises(RateLimitExceededError):
        limiter.check("user_a")


def test_rate_limit_error_carries_identity_and_retry_after():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=10)
    limiter.check("user_a")

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.check("user_a")

    assert exc_info.value.identity == "user_a"
    assert exc_info.value.retry_after_seconds > 0


def test_different_identities_have_independent_limits():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=10)

    limiter.check("user_a")
    limiter.check("user_b")  # different identity, should not raise


def test_window_expires_and_allows_new_requests():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=0.05)

    limiter.check("user_a")
    time.sleep(0.1)
    limiter.check("user_a")  # window has expired, should not raise
