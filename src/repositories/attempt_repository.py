"""
Quiz attempt repository (Repository Pattern).

Records real per-question answer outcomes (correct/incorrect) so
Analytics can compute a genuine "average score", "best performance",
and "weakest category" instead of substituting the LLM's own
confidence score for user performance - those are two different
things and conflating them would be exactly the kind of fake-data
substitution this app avoids.

If no attempts have been recorded yet (a fresh install, or a user who
only generates quizzes without answering them), every consumer of this
repository must show "not enough data yet", never a fabricated number.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AttemptEntry:
    sport: str
    difficulty: str
    question_index: int
    is_correct: bool
    answered_at: datetime


class AttemptRepository(Protocol):
    def record(self, request_id: str, sport: str, difficulty: str, question_index: int, is_correct: bool) -> None:
        ...

    def list_all(self, limit: int = 5000) -> list[AttemptEntry]:
        ...

    def count(self) -> int:
        ...


class SQLiteAttemptRepository:
    """SQLite-backed implementation of AttemptRepository."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, request_id: str, sport: str, difficulty: str, question_index: int, is_correct: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_attempts (request_id, sport, difficulty, question_index, is_correct, answered_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (request_id, sport, difficulty, question_index, int(is_correct), datetime.now(timezone.utc).isoformat()),
            )

    def list_all(self, limit: int = 5000) -> list[AttemptEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM quiz_attempts ORDER BY answered_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            AttemptEntry(
                sport=r["sport"],
                difficulty=r["difficulty"],
                question_index=r["question_index"],
                is_correct=bool(r["is_correct"]),
                answered_at=datetime.fromisoformat(r["answered_at"]),
            )
            for r in rows
        ]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM quiz_attempts").fetchone()
        return row["n"]