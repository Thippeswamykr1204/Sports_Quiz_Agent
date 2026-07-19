"""
Shared SQLite connection helper.

`sqlite3.Connection` used as a context manager (`with conn:`) only wraps
the transaction - it commits on success / rolls back on error, but it
does NOT close the connection. Every repository in this codebase used
to call `sqlite3.connect(...)` fresh per method and rely on `with conn:`
alone, which left each connection (and its OS file descriptor) open
until garbage collection. `sqlite_connection` gives repositories the
exact same call-site shape (`with sqlite_connection(path) as conn:`)
while guaranteeing the connection is always closed.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def sqlite_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Opens a SQLite connection with Row access, commits/rolls back, and closes it."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()