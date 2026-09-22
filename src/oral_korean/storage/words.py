"""The vocabulary's repository: words, their tags, their memory state and their history.

Storage persists what it is given and decides nothing. It does not seed a familiarity level
(the caller asks `srs/` for the seed and hands it over, to be written in the same transaction
as the word), it does not normalise a tag filter, and it validates nothing a word draft has
already validated. The one rule it enforces itself is the one only it can see: a word's
match key is unique across everything stored.

Recording an answered review, and the due and new queries, arrive with their consumer in
`vocab-sessions`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from oral_korean.exercises.vocab_words import VocabularyWord, WordDraft
from oral_korean.korean import hangul
from oral_korean.srs.memory import Familiarity, Grade, MemoryState, ReviewRecord
from oral_korean.storage.database import Database

_WORD_COLUMNS: Final = (
    "id, korean, translations, familiarity, added_at, "
    "stability, difficulty, next_review, last_review, review_count, lapse_count"
)
_REVIEW_COLUMNS: Final = (
    "grade, reviewed_at, is_seed, recall_before, stability, difficulty, next_review"
)

type _Row = tuple[Any, ...]
"""A row as `sqlite3` returns it: untyped, so each column is converted where it is read."""


class DuplicateWordError(ValueError):
    """A word would share its match key with one already stored, or earlier in its batch.

    Attributes:
        korean: the Korean of the word already there, as it is stored.
    """

    def __init__(self, korean: str) -> None:
        self.korean = korean
        super().__init__(f"{korean} is already in the vocabulary.")


@dataclass(frozen=True)
class TagCount:
    """A tag and how many words carry it."""

    tag: str
    count: int


class WordStore:
    """Words in one database, each operation its own unit of work."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add_words(
        self,
        entries: Sequence[tuple[WordDraft, tuple[MemoryState, ReviewRecord] | None]],
        at: datetime,
    ) -> tuple[VocabularyWord, ...]:
        """Store every draft, added at `at`, or none of them; the stored words, in order.

        Each draft comes with what `srs.memory.seed` returned for it: its initial memory state
        and seed record, written with the word, or `None` for a word added as new.

        Raises:
            DuplicateWordError: a draft collides with a stored word or an earlier draft.
            ValueError: `at` is naive.
        """
        added_at = _as_text(at)
        with self._database.transaction() as connection:
            ids: list[int] = []
            for draft, seeded in entries:
                # Earlier drafts are already inserted, and this connection sees its own
                # uncommitted rows, so one lookup covers the store and the batch alike.
                existing = _korean_with_key(connection, draft.match_key)
                if existing is not None:
                    raise DuplicateWordError(existing)
                ids.append(_insert_word(connection, draft, seeded, added_at))
            return tuple(_read_words(connection, ids))

    def get_word(self, word_id: int) -> VocabularyWord | None:
        """The word with this id, or `None` if there is none."""
        with self._database.transaction() as connection:
            found = _read_words(connection, [word_id])
        return found[0] if found else None

    def list_words(self, *, tag: str | None = None) -> tuple[VocabularyWord, ...]:
        """Every word, or every word carrying `tag` exactly, in the order they were added."""
        with self._database.transaction() as connection:
            if tag is None:
                rows = connection.execute("SELECT id FROM words ORDER BY id")
            else:
                rows = connection.execute(
                    "SELECT word_id FROM word_tags WHERE tag = ? ORDER BY word_id", (tag,)
                )
            return tuple(_read_words(connection, [row[0] for row in rows]))

    def update_word(
        self, word_id: int, korean: str, translations: tuple[str, ...], tags: tuple[str, ...]
    ) -> VocabularyWord | None:
        """Replace a word's Korean, translations and tags; `None` if there is no such word.

        The values are stored as given: the Korean in display form and the tags normalised,
        as a word draft holds them. Familiarity, memory, history and the adding instant stay.

        Raises:
            DuplicateWordError: another word already has the new Korean's match key.
        """
        key = hangul.match_key(korean)
        with self._database.transaction() as connection:
            if not _read_words(connection, [word_id]):
                return None
            other = connection.execute(
                "SELECT korean FROM words WHERE match_key = ? AND id != ?", (key, word_id)
            ).fetchone()
            if other is not None:
                raise DuplicateWordError(other[0])
            connection.execute(
                "UPDATE words SET korean = ?, match_key = ?, translations = ? WHERE id = ?",
                (korean, key, _translations_as_text(translations), word_id),
            )
            connection.execute("DELETE FROM word_tags WHERE word_id = ?", (word_id,))
            _insert_tags(connection, word_id, tags)
            return _read_words(connection, [word_id])[0]

    def delete_word(self, word_id: int) -> bool:
        """Delete a word with its tags and history; `False` if there was no such word."""
        with self._database.transaction() as connection:
            cursor = connection.execute("DELETE FROM words WHERE id = ?", (word_id,))
            return cursor.rowcount > 0

    def tag_counts(self) -> tuple[TagCount, ...]:
        """Every tag in use, with the number of words carrying it, sorted by tag."""
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT tag, COUNT(*) FROM word_tags GROUP BY tag ORDER BY tag"
            ).fetchall()
        return tuple(TagCount(tag=tag, count=count) for tag, count in rows)

    def history(self, word_id: int) -> tuple[ReviewRecord, ...]:
        """A word's seed and answers, oldest first; `()` for an unknown word."""
        with self._database.transaction() as connection:
            rows = connection.execute(
                f"SELECT {_REVIEW_COLUMNS} FROM reviews WHERE word_id = ? "
                "ORDER BY reviewed_at, id",
                (word_id,),
            ).fetchall()
        return tuple(_review_from_row(row) for row in rows)


def _korean_with_key(connection: sqlite3.Connection, key: str) -> str | None:
    """The stored Korean whose match key is `key`, if any."""
    row = connection.execute("SELECT korean FROM words WHERE match_key = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def _insert_word(
    connection: sqlite3.Connection,
    draft: WordDraft,
    seeded: tuple[MemoryState, ReviewRecord] | None,
    added_at: str,
) -> int:
    """Insert one word, its tags and its seed record; its new id."""
    state = None if seeded is None else seeded[0]
    cursor = connection.execute(
        "INSERT INTO words (korean, match_key, translations, familiarity, added_at, "
        "stability, difficulty, next_review, last_review, review_count, lapse_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            draft.korean,
            draft.match_key,
            _translations_as_text(draft.translations),
            draft.familiarity.value,
            added_at,
            *_memory_as_row(state),
        ),
    )
    word_id = cursor.lastrowid
    if word_id is None:
        # An INSERT always sets it; this narrows the type and says so.
        raise RuntimeError("SQLite returned no id for an inserted word")
    _insert_tags(connection, word_id, draft.tags)
    if seeded is not None:
        _insert_review(connection, word_id, seeded[1])
    return word_id


def _insert_tags(connection: sqlite3.Connection, word_id: int, tags: Iterable[str]) -> None:
    connection.executemany(
        "INSERT INTO word_tags (word_id, tag) VALUES (?, ?)", [(word_id, tag) for tag in tags]
    )


def _insert_review(connection: sqlite3.Connection, word_id: int, record: ReviewRecord) -> None:
    connection.execute(
        f"INSERT INTO reviews (word_id, {_REVIEW_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            word_id,
            record.grade.value,
            _as_text(record.reviewed_at),
            int(record.is_seed),
            record.recall_before,
            record.stability,
            record.difficulty,
            _as_text(record.next_review),
        ),
    )


def _read_words(connection: sqlite3.Connection, ids: Sequence[int]) -> list[VocabularyWord]:
    """The words with these ids, in the order given, skipping any that do not exist.

    No ids is fine: SQLite reads an empty `IN ()` as matching nothing.
    """
    placeholders = ", ".join("?" * len(ids))
    rows = connection.execute(
        f"SELECT {_WORD_COLUMNS} FROM words WHERE id IN ({placeholders})", ids
    ).fetchall()
    tags: dict[int, list[str]] = {}
    for word_id, tag in connection.execute(
        f"SELECT word_id, tag FROM word_tags WHERE word_id IN ({placeholders}) ORDER BY tag",
        ids,
    ):
        tags.setdefault(word_id, []).append(tag)
    by_id = {row[0]: _word_from_row(row, tuple(tags.get(row[0], ()))) for row in rows}
    return [by_id[word_id] for word_id in ids if word_id in by_id]


def _word_from_row(row: _Row, tags: tuple[str, ...]) -> VocabularyWord:
    (word_id, korean, translations, familiarity, added_at, *memory) = row
    return VocabularyWord(
        id=word_id,
        korean=korean,
        translations=tuple(json.loads(translations)),
        tags=tags,
        familiarity=Familiarity(familiarity),
        added_at=_from_text(added_at),
        memory=_memory_from_row(memory),
    )


def _memory_as_row(state: MemoryState | None) -> tuple[object, ...]:
    if state is None:
        return (None,) * 6
    return (
        state.stability,
        state.difficulty,
        _as_text(state.next_review),
        _as_text(state.last_review),
        state.review_count,
        state.lapse_count,
    )


def _memory_from_row(memory: Sequence[Any]) -> MemoryState | None:
    stability, difficulty, next_review, last_review, review_count, lapse_count = memory
    if stability is None:
        return None
    return MemoryState(
        stability=stability,
        difficulty=difficulty,
        next_review=_from_text(next_review),
        last_review=_from_text(last_review),
        review_count=review_count,
        lapse_count=lapse_count,
    )


def _review_from_row(row: _Row) -> ReviewRecord:
    grade, reviewed_at, is_seed, recall_before, stability, difficulty, next_review = row
    return ReviewRecord(
        grade=Grade(grade),
        reviewed_at=_from_text(reviewed_at),
        is_seed=bool(is_seed),
        recall_before=recall_before,
        stability=stability,
        difficulty=difficulty,
        next_review=_from_text(next_review),
    )


def _translations_as_text(translations: Sequence[str]) -> str:
    """A JSON array, non-ASCII kept as is so the file stays readable."""
    return json.dumps(list(translations), ensure_ascii=False)


def _as_text(at: datetime) -> str:
    """`at` as ISO-8601 UTC text with microseconds: one fixed format that sorts in time order.

    Raises:
        ValueError: `at` is naive.
    """
    if at.utcoffset() is None:
        raise ValueError(f"A timezone-aware datetime is needed, got the naive {at.isoformat()}.")
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def _from_text(text: str) -> datetime:
    """A stored instant, aware, with `timezone.utc` itself as its tzinfo (fsrs checks it)."""
    return datetime.fromisoformat(text).astimezone(UTC)
