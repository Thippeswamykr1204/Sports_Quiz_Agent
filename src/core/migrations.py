"""
Tiny, dependency-free SQLite migration runner.

Real migration mechanism (versioned, idempotent, forward-only) rather
than a bare `CREATE TABLE IF NOT EXISTS` scattered in repository code -
this is the single place schema changes for quiz_history.db get made and
tracked, so future changes are additive migrations, not silent rewrites.
"""

import sqlite3
from pathlib import Path

from src.core.logging import get_logger

logger = get_logger("migrations")

# Ordered list of (version, sql). Never edit an already-shipped entry -
# append a new (version, sql) tuple for any future schema change.
_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS quiz_history (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            sport TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            question_count INTEGER NOT NULL,
            confidence_avg REAL NOT NULL,
            generation_time_ms REAL,
            prompt_version TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE INDEX IF NOT EXISTS idx_quiz_history_sport ON quiz_history(sport);
        CREATE INDEX IF NOT EXISTS idx_quiz_history_difficulty ON quiz_history(difficulty);
        CREATE INDEX IF NOT EXISTS idx_quiz_history_generated_at ON quiz_history(generated_at);
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            sport TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            question_index INTEGER NOT NULL,
            is_correct INTEGER NOT NULL,
            answered_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_quiz_attempts_sport ON quiz_attempts(sport);
        CREATE INDEX IF NOT EXISTS idx_quiz_attempts_answered_at ON quiz_attempts(answered_at);
        """,
    ),
    (
        4,
        """
        ALTER TABLE quiz_history ADD COLUMN chunks_used INTEGER DEFAULT NULL;
        ALTER TABLE quiz_history ADD COLUMN sources_count INTEGER DEFAULT NULL;
        """,
    ),
    (
        5,
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
]


def apply_migrations(db_path: Path) -> None:
    """Creates the DB file's parent dir if needed and applies any pending migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

        for version, sql in _MIGRATIONS:
            if version in applied:
                continue
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            conn.commit()
            logger.info("migration_applied", version=version)
    finally:
        conn.close()