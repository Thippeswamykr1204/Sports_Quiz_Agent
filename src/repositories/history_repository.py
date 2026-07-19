"""
Quiz History repository (Repository Pattern - same discipline as
fact_repository.py / web_repository.py).

QuizHistoryRepository is the interface the service layer depends on.
SQLiteHistoryRepository is the current implementation - swapping to
Postgres later means writing a new class that satisfies this Protocol,
no changes anywhere else (Simplicity Guard: SQLite is the right size for
a single-process app; swap the implementation, not the architecture, if
this ever needs multi-writer scale).

Full quiz payload (questions, options, answers, sources) is stored as a
JSON blob - the columns alongside it (sport, difficulty, confidence_avg,
generated_at, ...) are what search/filter/sort actually query against,
so this isn't "no schema", it's "denormalized for a single read-heavy
history view" (Simplicity Guard again - a normalized questions/sources
table buys nothing here and doubles the join complexity for a feature
that's read far more than written).
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from src.core.logging import get_logger
from src.schemas.quiz import Quiz

logger = get_logger("history_repository")

SortField = Literal["generated_at", "confidence_avg", "sport", "difficulty"]
SortOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class HistoryFilter:
    """All fields optional - None means "don't filter on this"."""

    search_text: str | None = None
    sport: str | None = None
    difficulty: str | None = None
    min_confidence: float | None = None
    sort_by: SortField = "generated_at"
    sort_order: SortOrder = "desc"
    limit: int = 100


@dataclass(frozen=True)
class HistoryEntry:
    """One row's summary - cheap to list without deserializing the full Quiz."""

    id: str
    request_id: str
    sport: str
    difficulty: str
    question_count: int
    confidence_avg: float
    generation_time_ms: float | None
    prompt_version: str
    generated_at: datetime
    created_at: datetime
    chunks_used: int | None = None
    sources_count: int | None = None


class QuizHistoryRepository(Protocol):
    """Interface the service layer depends on - never raw sqlite3 outside this file."""

    def save(self, quiz: Quiz, chunks_used: int | None = None, sources_count: int | None = None) -> str:
        """Persists a quiz, returns its history id."""
        ...

    def list(self, filters: HistoryFilter) -> list[HistoryEntry]:
        ...

    def get(self, history_id: str) -> Quiz | None:
        """Returns the full stored Quiz (with questions/sources) or None."""
        ...

    def delete(self, history_id: str) -> bool:
        ...

    def count(self) -> int:
        ...


def _row_to_entry(row: sqlite3.Row) -> HistoryEntry:
    columns = row.keys()
    return HistoryEntry(
        id=row["id"],
        request_id=row["request_id"],
        sport=row["sport"],
        difficulty=row["difficulty"],
        question_count=row["question_count"],
        confidence_avg=row["confidence_avg"],
        generation_time_ms=row["generation_time_ms"],
        prompt_version=row["prompt_version"],
        generated_at=datetime.fromisoformat(row["generated_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        chunks_used=row["chunks_used"] if "chunks_used" in columns else None,
        sources_count=row["sources_count"] if "sources_count" in columns else None,
    )


class SQLiteHistoryRepository:
    """SQLite-backed implementation of QuizHistoryRepository."""

    _ALLOWED_SORT_COLUMNS = {"generated_at", "confidence_avg", "sport", "difficulty"}

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, quiz: Quiz, chunks_used: int | None = None, sources_count: int | None = None) -> str:
        history_id = str(uuid.uuid4())
        confidence_avg = sum(q.confidence for q in quiz.questions) / len(quiz.questions)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_history (
                    id, request_id, sport, difficulty, question_count,
                    confidence_avg, generation_time_ms, prompt_version,
                    generated_at, created_at, payload_json, chunks_used, sources_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    quiz.request_id,
                    quiz.sport.value,
                    quiz.difficulty.value,
                    len(quiz.questions),
                    confidence_avg,
                    quiz.generation_time_ms,
                    quiz.prompt_version,
                    quiz.generated_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    quiz.model_dump_json(),
                    chunks_used,
                    sources_count,
                ),
            )
        logger.info("history_saved", history_id=history_id, sport=quiz.sport.value)
        return history_id

    def list(self, filters: HistoryFilter) -> list[HistoryEntry]:
        sort_column = filters.sort_by if filters.sort_by in self._ALLOWED_SORT_COLUMNS else "generated_at"
        sort_order = "ASC" if filters.sort_order == "asc" else "DESC"

        clauses: list[str] = []
        params: list[object] = []

        if filters.sport:
            clauses.append("sport = ?")
            params.append(filters.sport)
        if filters.difficulty:
            clauses.append("difficulty = ?")
            params.append(filters.difficulty)
        if filters.min_confidence is not None:
            clauses.append("confidence_avg >= ?")
            params.append(filters.min_confidence)
        if filters.search_text:
            clauses.append("payload_json LIKE ?")
            params.append(f"%{filters.search_text}%")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # sort_column/sort_order are whitelisted above, never user-interpolated raw.
        query = (
            f"SELECT * FROM quiz_history {where} "
            f"ORDER BY {sort_column} {sort_order} LIMIT ?"
        )
        params.append(filters.limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get(self, history_id: str) -> Quiz | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM quiz_history WHERE id = ?", (history_id,)
            ).fetchone()
        if row is None:
            return None
        return Quiz.model_validate_json(row["payload_json"])

    def delete(self, history_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM quiz_history WHERE id = ?", (history_id,))
        return cursor.rowcount > 0

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM quiz_history").fetchone()
        return row["n"]