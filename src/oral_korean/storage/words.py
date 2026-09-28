"""The vocabulary's repository: words, their tags, their memory state and their history.

Storage persists what it is given and decides nothing. It does not seed a familiarity level
(the caller asks `srs/` for the seed and hands it over, to be written in the same transaction
as the word), it does not normalise a tag filter, and it validates nothing a word draft has
already validated. The one rule it enforces itself is the one only it can see: a word's
match key is unique across everything stored.

An answered review is recorded as given too: the caller grades it with `srs/` and hands over
the new state, its record and how the question was asked, written in one transaction.

A word has one memory per direction, each a row of `direction_memories` (migration 3); a
direction never seeded nor answered has no row. The memory columns on `words` hold migration 1's
single memory, left in place and never read or written again.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from oral_korean.exercises.vocab import AnswerMode, Direction
from oral_korean.exercises.vocab_words import VocabularyWord, WordDraft, same_memory
from oral_korean.korean import hangul
from oral_korean.srs.memory import Familiarity, Grade, MemoryState, ReviewRecord
from oral_korean.storage.database import Database

_WORD_COLUMNS: Final = "id, korean, translations, familiarity, added_at"
_MEMORY_COLUMNS: Final = (
    "stability, difficulty, next_review, last_review, review_count, lapse_count"
)
_REVIEW_COLUMNS: Final = (
    "grade, reviewed_at, is_seed, recall_before, stability, difficulty, next_review"
)
_ANSWER_COLUMNS: Final = "direction, answer_mode, correct"
"""Added by migration 2; a seed's row leaves them null, so inserting one never names them."""

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


class QueueOrderError(ValueError):
    """A learn-queue order the store refuses: an unknown or repeated id, or a word with
    nothing left to learn. The message names ids only, never a word's text."""


@dataclass(frozen=True)
class AnswerContext:
    """How an answered review was asked, and whether the answer was right."""

    direction: Direction
    mode: AnswerMode
    correct: bool


@dataclass(frozen=True)
class HistoryRow:
    """One entry of a word's history: the review, and how it was asked (`None` for a seed)."""

    record: ReviewRecord
    answer: AnswerContext | None


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

    def get_words(self, word_ids: Sequence[int]) -> tuple[VocabularyWord, ...]:
        """The words with these ids, in the order given, skipping any that do not exist."""
        with self._database.transaction() as connection:
            return tuple(_read_words(connection, word_ids))

    def list_words(
        self,
        *,
        tags: Collection[str] = (),
        match_all: bool = False,
        exclude: Collection[str] = (),
    ) -> tuple[VocabularyWord, ...]:
        """The words carrying any of `tags` (all of them with `match_all`) and none of
        `exclude`, tags matched exactly, in the order they were added. No `tags` means no
        condition on them: every word, less the excluded ones."""
        conditions = ["1"]
        included, parameters = _in_list("tag", tags)
        excluded, excluded_parameters = _in_list("exclude", exclude)
        parameters.update(excluded_parameters)
        if tags and match_all:
            parameters["tag_count"] = len(set(tags))
            conditions.append(
                "(SELECT COUNT(DISTINCT tag) FROM word_tags "
                f"WHERE word_id = words.id AND tag IN ({included})) = :tag_count"
            )
        elif tags:
            conditions.append(f"id IN (SELECT word_id FROM word_tags WHERE tag IN ({included}))")
        if exclude:
            conditions.append(
                f"id NOT IN (SELECT word_id FROM word_tags WHERE tag IN ({excluded}))"
            )
        return self._select_words(
            " AND ".join(conditions), parameters, order="id", tag=None, limit=None
        )

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

    def history(self, word_id: int) -> tuple[HistoryRow, ...]:
        """A word's seed and answers, oldest first; `()` for an unknown word."""
        with self._database.transaction() as connection:
            rows = connection.execute(
                f"SELECT {_REVIEW_COLUMNS}, {_ANSWER_COLUMNS} FROM reviews WHERE word_id = ? "
                "ORDER BY reviewed_at, id",
                (word_id,),
            ).fetchall()
        return tuple(_history_row(row) for row in rows)

    def record_answer(
        self, word_id: int, state: MemoryState, record: ReviewRecord, answer: AnswerContext
    ) -> bool:
        """Write a word's new memory state and the history row of the answer that led to it,
        both or neither; `False`, with nothing written, if the word no longer exists.

        Raises:
            ValueError: a datetime in `state` or `record` is naive.
        """
        with self._database.transaction() as connection:
            exists = connection.execute("SELECT 1 FROM words WHERE id = ?", (word_id,))
            if exists.fetchone() is None:
                return False
            _write_memory(connection, word_id, answer.direction, state)
            _insert_review(connection, word_id, record, answer)
            return True

    def new_words(
        self,
        *,
        tag: str | None = None,
        directions: Collection[Direction] = tuple(Direction),
        limit: int,
    ) -> tuple[VocabularyWord, ...]:
        """Up to `limit` words with no memory yet in at least one of `directions`, in learn
        queue order, optionally with `tag`: the top of `learn_queue`."""
        condition, parameters = _learnable(directions)
        return self._select_words(condition, parameters, order=_QUEUE_ORDER, tag=tag, limit=limit)

    def learn_queue(
        self, *, tag: str | None = None, directions: Collection[Direction] = tuple(Direction)
    ) -> tuple[VocabularyWord, ...]:
        """Every word with no memory yet in at least one of `directions`, in the order the
        user set, optionally with `tag`."""
        condition, parameters = _learnable(directions)
        return self._select_words(condition, parameters, order=_QUEUE_ORDER, tag=tag, limit=None)

    def reorder_learn_queue(self, word_ids: Sequence[int]) -> None:
        """Move these words to the top of the learn queue, in this order; every other word
        keeps its place relative to the others, after them.

        Raises:
            QueueOrderError: an id is repeated or unknown, or its word has a memory in every
                direction, so nothing is left to learn; nothing is changed.
        """
        if len(set(word_ids)) != len(word_ids):
            raise QueueOrderError("The same word is listed twice.")
        with self._database.transaction() as connection:
            queue = [
                row[0]
                for row in connection.execute(
                    "SELECT word_id FROM learn_queue ORDER BY position, word_id"
                )
            ]
            unknown = sorted(set(word_ids) - set(queue))
            if unknown:
                raise QueueOrderError(f"No word with id {', '.join(map(str, unknown))}.")
            placeholders = ", ".join("?" * len(word_ids))
            learned = sorted(
                row[0]
                for row in connection.execute(
                    "SELECT word_id FROM direction_memories "
                    f"WHERE word_id IN ({placeholders}) GROUP BY word_id HAVING COUNT(*) = ?",
                    (*word_ids, len(Direction)),
                )
            )
            if learned:
                raise QueueOrderError(
                    f"Nothing is left to learn of word {', '.join(map(str, learned))}."
                )
            moved = set(word_ids)
            order = [*word_ids, *(word_id for word_id in queue if word_id not in moved)]
            connection.executemany(
                "UPDATE learn_queue SET position = ? WHERE word_id = ?",
                list(enumerate(order, start=1)),
            )

    def due_words(
        self,
        at: datetime,
        *,
        tag: str | None = None,
        directions: Collection[Direction] = tuple(Direction),
        limit: int,
    ) -> tuple[VocabularyWord, ...]:
        """Up to `limit` words with a memory due at or before `at` in at least one of
        `directions`, the most overdue first, optionally with `tag`.

        Raises:
            ValueError: `at` is naive.
        """
        earliest, parameters = _earliest_review(directions)
        parameters["at"] = _as_text(at)
        return self._select_words(
            f"{earliest} <= :at", parameters, order=f"{earliest}, id", tag=tag, limit=limit
        )

    def review_candidates(
        self, *, tag: str | None = None, directions: Collection[Direction] = tuple(Direction)
    ) -> tuple[VocabularyWord, ...]:
        """Every word with a memory in at least one of `directions`, optionally with `tag`,
        by the earliest next review among those: at any instant, the due words come first,
        the most overdue first, then the others, the soonest first."""
        earliest, parameters = _earliest_review(directions)
        return self._select_words(
            f"{earliest} IS NOT NULL", parameters, order=f"{earliest}, id", tag=tag, limit=None
        )

    def _select_words(
        self,
        condition: str,
        parameters: dict[str, object],
        *,
        order: str,
        tag: str | None,
        limit: int | None,
    ) -> tuple[VocabularyWord, ...]:
        """The words matching `condition` (and carrying `tag`, if given), in `order`, capped
        at `limit` unless it is `None`.

        `condition` and `order` are this module's own SQL fragments, never user input, and
        take their values from `parameters` by name.
        """
        if tag is not None:
            condition += " AND id IN (SELECT word_id FROM word_tags WHERE tag = :tag)"
        with self._database.transaction() as connection:
            rows = connection.execute(
                f"SELECT id FROM words WHERE {condition} ORDER BY {order} LIMIT :limit",
                # SQLite reads a negative limit as none.
                {**parameters, "tag": tag, "limit": -1 if limit is None else limit},
            )
            return tuple(_read_words(connection, [row[0] for row in rows]))


_QUEUE_ORDER: Final = "(SELECT position FROM learn_queue WHERE word_id = words.id), id"
"""Learn queue order, as an `ORDER BY` over `words`."""


def _learnable(directions: Collection[Direction]) -> tuple[str, dict[str, object]]:
    """The condition, over `words`, of a word without memory in one of `directions`."""
    wanted, parameters = _direction_parameters(directions)
    learned = (
        "SELECT COUNT(*) FROM direction_memories "
        f"WHERE word_id = words.id AND direction IN ({wanted})"
    )
    parameters["wanted"] = len(set(directions))
    return f"({learned}) < :wanted", parameters


def _earliest_review(directions: Collection[Direction]) -> tuple[str, dict[str, object]]:
    """The expression, over `words`, of a word's earliest next review among `directions`:
    null when it has no memory in any of them."""
    wanted, parameters = _direction_parameters(directions)
    earliest = (
        "(SELECT MIN(next_review) FROM direction_memories "
        f"WHERE word_id = words.id AND direction IN ({wanted}))"
    )
    return earliest, parameters


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
    """Insert one word, its tags, its place at the end of the learn queue, and its seed: the
    same memory in every direction, and one history row with no direction, meaning all of
    them. Its new id."""
    cursor = connection.execute(
        "INSERT INTO words (korean, match_key, translations, familiarity, added_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            draft.korean,
            draft.match_key,
            _translations_as_text(draft.translations),
            draft.familiarity.value,
            added_at,
        ),
    )
    word_id = cursor.lastrowid
    if word_id is None:
        # An INSERT always sets it; this narrows the type and says so.
        raise RuntimeError("SQLite returned no id for an inserted word")
    _insert_tags(connection, word_id, draft.tags)
    connection.execute(
        "INSERT INTO learn_queue (word_id, position) "
        "SELECT ?, COALESCE(MAX(position), 0) + 1 FROM learn_queue",
        (word_id,),
    )
    if seeded is not None:
        state, record = seeded
        for direction in Direction:
            _write_memory(connection, word_id, direction, state)
        _insert_review(connection, word_id, record)
    return word_id


def _write_memory(
    connection: sqlite3.Connection, word_id: int, direction: Direction, state: MemoryState
) -> None:
    """Set one direction's memory, whether or not it had one."""
    connection.execute(
        f"INSERT OR REPLACE INTO direction_memories (word_id, direction, {_MEMORY_COLUMNS}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (word_id, direction.value, *_memory_as_row(state)),
    )


def _direction_parameters(directions: Collection[Direction]) -> tuple[str, dict[str, object]]:
    """`directions` as named SQL placeholders for an `IN (...)` list, and their values."""
    return _in_list("direction", [direction.value for direction in directions])


def _in_list(prefix: str, values: Iterable[str]) -> tuple[str, dict[str, object]]:
    """`values` as named SQL placeholders for an `IN (...)` list, each name starting with
    `prefix`, and their values by name."""
    named: dict[str, object] = {f"{prefix}_{index}": value for index, value in enumerate(values)}
    return ", ".join(f":{name}" for name in named), named


def _insert_tags(connection: sqlite3.Connection, word_id: int, tags: Iterable[str]) -> None:
    connection.executemany(
        "INSERT INTO word_tags (word_id, tag) VALUES (?, ?)", [(word_id, tag) for tag in tags]
    )


def _insert_review(
    connection: sqlite3.Connection,
    word_id: int,
    record: ReviewRecord,
    answer: AnswerContext | None = None,
) -> None:
    """Insert one history row; the answer columns only for an answer, so a seed can still be
    written to a file at schema version 1."""
    columns = _REVIEW_COLUMNS
    values: tuple[object, ...] = (
        word_id,
        record.grade.value,
        _as_text(record.reviewed_at),
        int(record.is_seed),
        record.recall_before,
        record.stability,
        record.difficulty,
        _as_text(record.next_review),
    )
    if answer is not None:
        columns += f", {_ANSWER_COLUMNS}"
        values += (answer.direction.value, answer.mode.value, int(answer.correct))
    placeholders = ", ".join("?" * len(values))
    connection.execute(f"INSERT INTO reviews (word_id, {columns}) VALUES ({placeholders})", values)


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
    memories: dict[int, dict[Direction, MemoryState | None]] = {}
    for word_id, direction, *memory in connection.execute(
        f"SELECT word_id, direction, {_MEMORY_COLUMNS} FROM direction_memories "
        f"WHERE word_id IN ({placeholders})",
        ids,
    ):
        states = memories.setdefault(word_id, same_memory(None))
        states[Direction(direction)] = _memory_from_row(memory)
    by_id = {
        row[0]: _word_from_row(
            row, tuple(tags.get(row[0], ())), memories.get(row[0], same_memory(None))
        )
        for row in rows
    }
    return [by_id[word_id] for word_id in ids if word_id in by_id]


def _word_from_row(
    row: _Row, tags: tuple[str, ...], memories: dict[Direction, MemoryState | None]
) -> VocabularyWord:
    (word_id, korean, translations, familiarity, added_at) = row
    return VocabularyWord(
        id=word_id,
        korean=korean,
        translations=tuple(json.loads(translations)),
        tags=tags,
        familiarity=Familiarity(familiarity),
        added_at=_from_text(added_at),
        memories=memories,
    )


def _memory_as_row(state: MemoryState) -> tuple[object, ...]:
    return (
        state.stability,
        state.difficulty,
        _as_text(state.next_review),
        _as_text(state.last_review),
        state.review_count,
        state.lapse_count,
    )


def _memory_from_row(memory: Sequence[Any]) -> MemoryState:
    stability, difficulty, next_review, last_review, review_count, lapse_count = memory
    return MemoryState(
        stability=stability,
        difficulty=difficulty,
        next_review=_from_text(next_review),
        last_review=_from_text(last_review),
        review_count=review_count,
        lapse_count=lapse_count,
    )


def _history_row(row: _Row) -> HistoryRow:
    (
        grade,
        reviewed_at,
        is_seed,
        recall_before,
        stability,
        difficulty,
        next_review,
        direction,
        answer_mode,
        correct,
    ) = row
    record = ReviewRecord(
        grade=Grade(grade),
        reviewed_at=_from_text(reviewed_at),
        is_seed=bool(is_seed),
        recall_before=recall_before,
        stability=stability,
        difficulty=difficulty,
        next_review=_from_text(next_review),
    )
    answer = None
    if direction is not None:
        answer = AnswerContext(
            direction=Direction(direction), mode=AnswerMode(answer_mode), correct=bool(correct)
        )
    return HistoryRow(record=record, answer=answer)


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
