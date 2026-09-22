"""The SQLite file: opening it, one unit of work at a time, and migrating its schema.

stdlib `sqlite3`, no ORM: a single user, three tables, and rows mapped to the frozen domain
values by hand in this package. All SQL in the project lives under `storage/`, so moving to
another database would rewrite one package and no caller.

- **One connection per unit of work**, foreign keys switched on for each, committed on
  success, rolled back on any exception, closed always. No module-level connection: FastAPI
  runs sync routes in a threadpool.
- **Lazy.** Building a `Database` touches nothing; the first unit of work creates the parent
  directory, the file and the schema. Merely starting the app never writes to disk.
- **Default rollback journal, not WAL**: the file sits on a Docker Desktop bind mount from a
  Windows host, where WAL's shared-memory file is not reliable.
- **Numbered migrations.** `MIGRATIONS[n - 1]` takes a file from version `n - 1` to `n`, and
  the file's version is SQLite's `user_version`. Each pending migration runs in its own
  transaction together with the version bump, so a migration that fails halfway leaves both
  the schema and the version as they were. `executescript()` would commit an open transaction
  first under the legacy transaction control, so connections are opened in autocommit mode and
  every transaction is begun and ended explicitly. A file newer than the code is refused
  without being written to: guessing at a schema from the future risks the user's only copy.

**Shipped migrations are append-only.** A file in use has already run them, so editing one
changes nothing there and silently forks the schema everywhere else. Change the schema by
appending a migration.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

_MIGRATION_1: Final = """
CREATE TABLE words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    korean TEXT NOT NULL,
    match_key TEXT NOT NULL UNIQUE,
    translations TEXT NOT NULL,
    familiarity TEXT NOT NULL,
    added_at TEXT NOT NULL,
    stability REAL,
    difficulty REAL,
    next_review TEXT,
    last_review TEXT,
    review_count INTEGER,
    lapse_count INTEGER,
    CHECK (
        (stability IS NULL AND difficulty IS NULL AND next_review IS NULL
            AND last_review IS NULL AND review_count IS NULL AND lapse_count IS NULL)
        OR (stability IS NOT NULL AND difficulty IS NOT NULL AND next_review IS NOT NULL
            AND last_review IS NOT NULL AND review_count IS NOT NULL
            AND lapse_count IS NOT NULL)
    )
);

CREATE TABLE word_tags (
    word_id INTEGER NOT NULL REFERENCES words (id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (word_id, tag)
);

CREATE INDEX word_tags_by_tag ON word_tags (tag);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL REFERENCES words (id) ON DELETE CASCADE,
    reviewed_at TEXT NOT NULL,
    grade TEXT NOT NULL,
    is_seed INTEGER NOT NULL CHECK (is_seed IN (0, 1)),
    recall_before REAL,
    stability REAL NOT NULL,
    difficulty REAL NOT NULL,
    next_review TEXT NOT NULL
);

CREATE INDEX reviews_by_word ON reviews (word_id, reviewed_at);
"""
"""The vocabulary: words, their tags and their review history.

`AUTOINCREMENT` so an id is never reused: a browser tab holding a deleted word's id must not
come to point at a different word. Translations are a JSON array in one column, in order,
since no query filters on them. The memory columns are all null for a word never seeded nor
answered, or all set. Datetimes are ISO-8601 UTC text with microseconds, which sorts in time
order.
"""

MIGRATIONS: Final[tuple[str, ...]] = (_MIGRATION_1,)
"""Every migration, in order. Append-only once shipped: see the module docstring."""


class SchemaVersionError(RuntimeError):
    """The file was written by a newer version of the code, so this one will not open it."""


class Database:
    """One SQLite file, opened afresh for every unit of work."""

    def __init__(self, path: Path, *, migrations: Sequence[str] = MIGRATIONS) -> None:
        self._path = path
        self._migrations = tuple(migrations)
        self._migrated = False

    @property
    def path(self) -> Path:
        """Where the file is, or will be once the first unit of work creates it."""
        return self._path

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A connection inside one transaction, committed if the block completes.

        The first call on this object creates the directory and the file and brings the
        schema up to date. Any exception rolls back everything written in the block and is
        re-raised.

        Raises:
            SchemaVersionError: the file is newer than the code.
            sqlite3.Error: a migration or a statement failed.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, autocommit=True)
        try:
            # Only outside a transaction does SQLite honour this pragma.
            connection.execute("PRAGMA foreign_keys = ON")
            if not self._migrated:
                self._migrate(connection)
                self._migrated = True
            with _explicit_transaction(connection, "BEGIN"):
                yield connection
        finally:
            connection.close()

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Apply every pending migration, each in its own transaction with its version bump.

        The version is read again under a write lock before each step, so two first requests
        racing each other cannot both apply the same migration.
        """
        latest = len(self._migrations)
        while True:
            with _explicit_transaction(connection, "BEGIN IMMEDIATE"):
                current = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if current > latest:
                    raise SchemaVersionError(
                        f"{self._path} is at schema version {current}, but this code only "
                        f"knows versions up to {latest}. Run the newer code, or restore a "
                        "backup made by this version."
                    )
                if current == latest:
                    return
                connection.executescript(self._migrations[current])
                connection.execute(f"PRAGMA user_version = {current + 1}")


@contextmanager
def _explicit_transaction(connection: sqlite3.Connection, begin: str) -> Iterator[None]:
    """Run the block between `begin` and a commit, or a rollback if it raises."""
    connection.execute(begin)
    try:
        yield
    except BaseException:
        # SQLite may already have rolled back on its own after some errors.
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")
