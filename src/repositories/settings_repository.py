"""
Persisted user-settings repository (Repository Pattern).

Plain string key-value store - the service layer (settings_service.py)
owns typing/validation/parsing. A row only exists once the user has
explicitly overridden a default; absence of a row means "using the
environment/config default", not "zero" or "off".
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from src.core.db import sqlite_connection


class SettingsRepository(Protocol):
    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str) -> None:
        ...

    def get_all(self) -> dict[str, str]:
        ...

    def delete(self, key: str) -> bool:
        ...


class SQLiteSettingsRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self):
        return sqlite_connection(self._db_path)

    def get(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM user_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, datetime.now(timezone.utc).isoformat()),
            )

    def get_all(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM user_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def delete(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM user_settings WHERE key = ?", (key,))
        return cursor.rowcount > 0