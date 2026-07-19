"""
Cache wrapper around diskcache.

Isolates the caching library behind a small interface so quiz_service.py
depends on a Protocol, not diskcache directly — same Repository-style
discipline as the retrieval layer. Cache keys are scoped to
(sport, difficulty, date, prompt_version) so:
- a prompt version bump doesn't serve stale-format cached quizzes
- the cache naturally rotates daily without an explicit invalidation job
"""

from datetime import date
from pathlib import Path
from typing import Protocol

import diskcache

from src.core.logging import get_logger
from src.schemas.quiz import Difficulty, Quiz, Sport

logger = get_logger("cache")


class QuizCache(Protocol):
    """Interface for caching generated quizzes."""

    def get(self, sport: Sport, difficulty: Difficulty, prompt_version: str) -> Quiz | None:
        ...

    def set(
        self,
        sport: Sport,
        difficulty: Difficulty,
        prompt_version: str,
        quiz: Quiz,
        ttl_seconds: int,
    ) -> None:
        ...

    def clear(self) -> int:
        """Clears all cached quizzes. Returns the number of entries removed."""
        ...


def _build_key(sport: Sport, difficulty: Difficulty, prompt_version: str) -> str:
    today = date.today().isoformat()
    return f"quiz::{sport.value}::{difficulty.value}::{prompt_version}::{today}"


class DiskQuizCache:
    """diskcache-backed implementation of QuizCache."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache = diskcache.Cache(str(cache_dir))

    def get(self, sport: Sport, difficulty: Difficulty, prompt_version: str) -> Quiz | None:
        key = _build_key(sport, difficulty, prompt_version)
        raw = self._cache.get(key)
        if raw is None:
            logger.info("cache_miss", key=key)
            return None
        logger.info("cache_hit", key=key)
        return Quiz.model_validate_json(raw)

    def set(
        self,
        sport: Sport,
        difficulty: Difficulty,
        prompt_version: str,
        quiz: Quiz,
        ttl_seconds: int,
    ) -> None:
        key = _build_key(sport, difficulty, prompt_version)
        self._cache.set(key, quiz.model_dump_json(), expire=ttl_seconds)
        logger.info("cache_set", key=key, ttl_seconds=ttl_seconds)

    def clear(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        logger.info("cache_cleared", entries_removed=count)
        return count