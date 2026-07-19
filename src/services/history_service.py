"""
Quiz History service (Service Layer) - the only thing the UI talks to
for history features. Owns search/filter/sort composition, duplicate,
and export so that logic exists in exactly one place instead of being
re-implemented per view (Avoid Duplicate Code).
"""

from datetime import datetime, timezone

from src.repositories.history_repository import HistoryEntry, HistoryFilter, QuizHistoryRepository
from src.schemas.quiz import Quiz


class HistoryService:
    """Thin orchestration over QuizHistoryRepository - no sqlite/UI concerns here."""

    def __init__(self, repository: QuizHistoryRepository) -> None:
        self._repository = repository

    def record(self, quiz: Quiz) -> str:
        """Persists a freshly generated quiz. Called once, from QuizService.generate()."""
        return self._repository.save(quiz)

    def search(
        self,
        search_text: str | None = None,
        sport: str | None = None,
        difficulty: str | None = None,
        min_confidence: float | None = None,
        sort_by: str = "generated_at",
        sort_order: str = "desc",
        limit: int = 100,
    ) -> list[HistoryEntry]:
        filters = HistoryFilter(
            search_text=search_text or None,
            sport=sport,
            difficulty=difficulty,
            min_confidence=min_confidence,
            sort_by=sort_by,  # type: ignore[arg-type]
            sort_order=sort_order,  # type: ignore[arg-type]
            limit=limit,
        )
        return self._repository.list(filters)

    def get_full_quiz(self, history_id: str) -> Quiz | None:
        return self._repository.get(history_id)

    def delete(self, history_id: str) -> bool:
        return self._repository.delete(history_id)

    def duplicate(self, history_id: str) -> str | None:
        """
        Creates a new history row cloned from an existing one (new id,
        new timestamps, same questions/sport/difficulty). Returns the new
        history id, or None if the source doesn't exist.
        """
        original = self._repository.get(history_id)
        if original is None:
            return None

        clone = original.model_copy(
            update={"generated_at": datetime.now(timezone.utc)}
        )
        return self._repository.save(clone)

    def export_json(self, history_id: str) -> str | None:
        """Returns the quiz's full JSON (questions, answers, sources) or None if missing."""
        quiz = self._repository.get(history_id)
        if quiz is None:
            return None
        return quiz.model_dump_json(indent=2)

    def total_count(self) -> int:
        return self._repository.count()