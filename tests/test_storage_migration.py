"""Tests for the migrations that run on the user's existing file: 2 (vocab-sessions T03) and 3
(vocab-directions T01, one memory per word and direction).

Split from `test_storage.py` and `test_storage_reviews.py` only for pylint's module length.
Written before the implementation of migration 3; the contract:

- `MIGRATIONS` holds SQL scripts **or Python callables** taking the open `sqlite3.Connection`.
  A callable runs inside the same transaction as its `user_version` bump, so one that raises
  leaves neither its writes nor the bump. `Database(path, migrations=...)` takes both kinds.
- **Migration 3** (`MIGRATIONS[2]`, a callable) creates `direction_memories (word_id,
  direction, stability, difficulty, next_review, last_review, review_count, lapse_count)`, one
  row per word and direction **that has a memory**, and fills it by replaying each word's
  `reviews` rows:
  - a seed row: its stability, difficulty and next review become every direction's state, with
    `last_review` the seed's `reviewed_at` and both counts 0 (which is `seed(...)[0]` exactly);
  - answered rows in `reviewed_at, id` order: the row's direction's state becomes
    `apply_grade(state, grade, reviewed_at, fuzzing=False)`; a row with a null direction is
    replayed into all four, in its place in the order;
  - a direction with neither has no memory.
  `reviews` is left untouched, and so are the six old memory columns on `words`, which nothing
  reads or writes any more.

Files at an old version are built by `Database(path, migrations=MIGRATIONS[:n])`, then filled
with raw SQL shaped the way the code of that version wrote them (the word-level memory
columns hold the word-level replay, as version 2 kept them): the only way to have a version-2
file once the code writes version 3. Raw `sqlite3` access is used for that, and for reading
back what the domain API cannot show (a table's rows, the schema, the version). Expected states
are the ticket's replay, spelled out per test as `apply_grade` chains with fuzzing off.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_storage import T0, word

from oral_korean.exercises.vocab import AnswerMode
from oral_korean.exercises.vocab_words import Direction, same_memory
from oral_korean.korean import hangul
from oral_korean.srs.memory import (
    Familiarity,
    Grade,
    MemoryState,
    Phase,
    ReviewRecord,
    aggregate_statistics,
    apply_grade,
    seed,
)
from oral_korean.storage.database import MIGRATIONS, Database
from oral_korean.storage.words import AnswerContext, HistoryRow, WordStore

H2T = Direction.HANGUL_TO_TRANSLATION
T2H = Direction.TRANSLATION_TO_HANGUL
V2H = Direction.VOICE_TO_HANGUL
V2T = Direction.VOICE_TO_TRANSLATION
DAY = timedelta(days=1)

type Row = tuple[Any, ...]

OLD_WORD_COLUMNS = (
    "korean, match_key, translations, familiarity, added_at, stability, difficulty, "
    "next_review, last_review, review_count, lapse_count"
)
"""The `words` columns versions 1 and 2 wrote, the six memory columns last."""


class _Boom(Exception):
    """A marker exception, so a rollback test proves the real error is re-raised, not eaten."""


@dataclass(frozen=True)
class Answered:
    """One answered review as an older version recorded it; `direction` `None` for a row that
    predates migration 2's columns."""

    direction: Direction | None
    grade: Grade
    at: datetime


def text(at: datetime) -> str:
    """An instant as the stored format: ISO-8601 UTC with microseconds."""
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def file_at_version(tmp_path: Path, version: int) -> Path:
    """A fresh file migrated to `version` by the shipped steps, and no further."""
    path = tmp_path / "oral-korean.sqlite3"
    with Database(path, migrations=MIGRATIONS[:version]).transaction() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version
    return path


def seeded(familiarity: Familiarity) -> tuple[MemoryState, ReviewRecord]:
    """`seed(familiarity, T0)` with fuzzing off, asserted non-`None`."""
    result = seed(familiarity, T0, fuzzing=False)
    assert result is not None
    return result


def replayed(state: MemoryState | None, *steps: tuple[Grade, datetime]) -> MemoryState:
    """`state` after each `(grade, at)` in turn, fuzzing off: the ticket's replay, by hand."""
    assert steps, "at least one step"
    for grade, at in steps:
        state, _ = apply_grade(state, grade, at, fuzzing=False)
    assert state is not None
    return state


def memory_columns(state: MemoryState | None) -> tuple[object, ...]:
    if state is None:
        return (None,) * 6
    return (
        state.stability,
        state.difficulty,
        text(state.next_review),
        text(state.last_review),
        state.review_count,
        state.lapse_count,
    )


def insert_review(
    raw: sqlite3.Connection, word_id: int, record: ReviewRecord, answered: Answered | None
) -> None:
    """One `reviews` row; the answer columns (version 2) only for an answer with a direction."""
    columns = (
        "word_id, reviewed_at, grade, is_seed, recall_before, stability, difficulty, next_review"
    )
    values: tuple[object, ...] = (
        word_id,
        text(record.reviewed_at),
        record.grade.value,
        int(record.is_seed),
        record.recall_before,
        record.stability,
        record.difficulty,
        text(record.next_review),
    )
    if answered is not None and answered.direction is not None:
        right = answered.grade is not Grade.AGAIN
        mode = AnswerMode.TYPING if answered.grade is Grade.GOOD else AnswerMode.CHOICE
        columns += ", direction, answer_mode, correct"
        values += (answered.direction.value, mode.value, int(right))
    placeholders = ", ".join("?" * len(values))
    raw.execute(f"INSERT INTO reviews ({columns}) VALUES ({placeholders})", values)


def write_word(
    raw: sqlite3.Connection,
    korean: str,
    familiarity: Familiarity,
    answers: Sequence[Answered] = (),
    *,
    tags: Sequence[str] = (),
) -> int:
    """A word as an older version wrote it: its seed row, its answered rows in the order given,
    and the word-level memory columns holding the word-level replay in time order."""
    seed_pair = seed(familiarity, T0, fuzzing=False)
    state = None if seed_pair is None else seed_pair[0]
    records: dict[int, ReviewRecord] = {}
    for index, answered in sorted(enumerate(answers), key=lambda pair: pair[1].at):
        state, records[index] = apply_grade(state, answered.grade, answered.at, fuzzing=False)

    cursor = raw.execute(
        f"INSERT INTO words ({OLD_WORD_COLUMNS}) VALUES ({', '.join('?' * 11)})",
        (
            korean,
            hangul.match_key(korean),
            json.dumps(["x"]),
            familiarity.value,
            text(T0),
            *memory_columns(state),
        ),
    )
    word_id = cursor.lastrowid
    assert word_id is not None
    raw.executemany(
        "INSERT INTO word_tags (word_id, tag) VALUES (?, ?)", [(word_id, tag) for tag in tags]
    )
    if seed_pair is not None:
        insert_review(raw, word_id, seed_pair[1], None)
    for index, answered in enumerate(answers):
        insert_review(raw, word_id, records[index], answered)
    return word_id


def all_rows(path: Path, table: str) -> list[Row]:
    """Every row of `table`, in id order, read with a raw connection."""
    with closing(sqlite3.connect(path)) as raw:
        return raw.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()


def user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as raw:
        return int(raw.execute("PRAGMA user_version").fetchone()[0])


def table_names(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as raw:
        rows = raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def memory_rows(path: Path, word_id: int) -> int:
    with closing(sqlite3.connect(path)) as raw:
        return int(
            raw.execute(
                "SELECT COUNT(*) FROM direction_memories WHERE word_id = ?", (word_id,)
            ).fetchone()[0]
        )


def memories_of(store: WordStore, word_id: int) -> dict[Direction, MemoryState | None]:
    found = store.get_word(word_id)
    assert found is not None
    return dict(found.memories)


def migration_3() -> Any:
    """`MIGRATIONS[2]`, narrowed to the callable it must be."""
    step = MIGRATIONS[2]
    assert callable(step) and not isinstance(step, str)
    return step


# ---------------------------------------------------------------------------------
# The version-2 file every migration-3 test reads
# ---------------------------------------------------------------------------------

A_LITTLE_H2T = Answered(H2T, Grade.HARD, T0 + DAY)
A_LITTLE_V2H = Answered(V2H, Grade.AGAIN, T0 + DAY + timedelta(hours=2))
ONE_DIRECTION_V2T = Answered(V2T, Grade.HARD, T0 + timedelta(hours=3))
NULL_H2T = Answered(H2T, Grade.HARD, T0 + 2 * DAY)
NULL_ALL = Answered(None, Grade.GOOD, T0 + 3 * DAY)
NULL_V2T = Answered(V2T, Grade.AGAIN, T0 + 4 * DAY)
LATE_ROW = Answered(H2T, Grade.AGAIN, T0 + 2 * DAY)
EARLY_ROW = Answered(H2T, Grade.HARD, T0 + DAY)


@dataclass(frozen=True)
class Version2File:
    """A version-2 file holding one word per case, the snapshots taken before migrating, and a
    store over it that has not been opened yet."""

    path: Path
    ids: dict[str, int]
    reviews_before: list[Row]
    words_before: list[Row]

    def migrated(self) -> WordStore:
        store = WordStore(Database(self.path))
        store.list_words()  # the first unit of work migrates
        return store


def version_2_file(tmp_path: Path) -> Version2File:
    path = file_at_version(tmp_path, 2)
    with closing(sqlite3.connect(path)) as raw:
        ids = {
            "new": write_word(raw, word(200), Familiarity.NEW),
            "well": write_word(raw, word(201), Familiarity.WELL, tags=("food",)),
            "a_little": write_word(
                raw, word(202), Familiarity.A_LITTLE, [A_LITTLE_H2T, A_LITTLE_V2H]
            ),
            "one_direction": write_word(raw, word(203), Familiarity.NEW, [ONE_DIRECTION_V2T]),
            "null_direction": write_word(
                raw, word(204), Familiarity.WELL, [NULL_H2T, NULL_ALL, NULL_V2T]
            ),
            "out_of_order": write_word(raw, word(205), Familiarity.NEW, [LATE_ROW, EARLY_ROW]),
        }
        raw.commit()
    return Version2File(path, ids, all_rows(path, "reviews"), all_rows(path, "words"))


# ---------------------------------------------------------------------------------
# Migration 3: the replay
# ---------------------------------------------------------------------------------


def test_a_version_2_file_opens_at_the_latest_version(tmp_path: Path) -> None:
    """Migration 3 runs on first use, and the file ends at the code's version."""
    file = version_2_file(tmp_path)
    assert user_version(file.path) == 2  # sanity

    file.migrated()

    assert len(MIGRATIONS) >= 3
    assert user_version(file.path) == len(MIGRATIONS)
    assert "direction_memories" in table_names(file.path)


def test_a_new_word_never_answered_has_no_memory_in_any_direction(tmp_path: Path) -> None:
    """No seed and no answer: four directions without memory, and no row for any of them."""
    file = version_2_file(tmp_path)
    store = file.migrated()

    memories = memories_of(store, file.ids["new"])
    aggregate = aggregate_statistics(list(memories.values()), T0)

    assert memories == same_memory(None)
    assert (aggregate.phase, aggregate.score) == (Phase.NEW, None)
    assert memory_rows(file.path, file.ids["new"]) == 0


def test_a_word_seeded_well_never_answered_has_the_seed_in_all_four_directions(
    tmp_path: Path,
) -> None:
    """The seed row's figures, last reviewed at the seed, nothing counted: `seed`'s own state."""
    file = version_2_file(tmp_path)
    state, _ = seeded(Familiarity.WELL)
    store = file.migrated()

    memories = memories_of(store, file.ids["well"])

    assert memories == same_memory(state)
    assert {(m.review_count, m.lapse_count) for m in memories.values() if m} == {(0, 0)}
    assert memory_rows(file.path, file.ids["well"]) == 4
    found = store.get_word(file.ids["well"])
    assert found is not None
    assert found.tags == ("food",)


def test_answers_in_two_directions_replay_from_the_seed_and_leave_the_other_two(
    tmp_path: Path,
) -> None:
    """Seeded `a_little`, right by choice in hangul-to-translation, wrong in voice-to-Hangul:
    each answered direction is its own replay from the seed, the other two keep the seed."""
    file = version_2_file(tmp_path)
    seed_state, _ = seeded(Familiarity.A_LITTLE)
    store = file.migrated()

    memories = memories_of(store, file.ids["a_little"])

    assert memories == {
        H2T: replayed(seed_state, (Grade.HARD, A_LITTLE_H2T.at)),
        T2H: seed_state,
        V2H: replayed(seed_state, (Grade.AGAIN, A_LITTLE_V2H.at)),
        V2T: seed_state,
    }
    v2h = memories[V2H]
    assert v2h is not None
    assert (v2h.review_count, v2h.lapse_count) == (1, 1)


def test_a_new_word_answered_once_has_a_memory_in_that_direction_only(tmp_path: Path) -> None:
    """Replayed from no memory at all; the three other directions have none, and no row."""
    file = version_2_file(tmp_path)
    store = file.migrated()

    memories = memories_of(store, file.ids["one_direction"])

    assert memories == {
        H2T: None,
        T2H: None,
        V2H: None,
        V2T: replayed(None, (Grade.HARD, ONE_DIRECTION_V2T.at)),
    }
    assert memory_rows(file.path, file.ids["one_direction"]) == 1


def test_an_answer_with_no_direction_is_replayed_into_all_four_in_its_place(
    tmp_path: Path,
) -> None:
    """Seeded `well`; hangul-to-translation hard, then a row with no direction (good), then
    voice-to-translation again: the directionless row lands in all four, after the first
    answer and before the last."""
    file = version_2_file(tmp_path)
    seed_state, _ = seeded(Familiarity.WELL)
    everywhere = replayed(seed_state, (Grade.GOOD, NULL_ALL.at))
    store = file.migrated()

    memories = memories_of(store, file.ids["null_direction"])

    assert memories == {
        H2T: replayed(seed_state, (Grade.HARD, NULL_H2T.at), (Grade.GOOD, NULL_ALL.at)),
        T2H: everywhere,
        V2H: everywhere,
        V2T: replayed(everywhere, (Grade.AGAIN, NULL_V2T.at)),
    }


def test_answers_are_replayed_in_time_order_not_in_row_order(tmp_path: Path) -> None:
    """The later answer was stored first: the replay follows `reviewed_at`, as the history
    reads, whatever order the rows were inserted in."""
    file = version_2_file(tmp_path)
    store = file.migrated()

    memories = memories_of(store, file.ids["out_of_order"])

    assert memories[H2T] == replayed(None, (Grade.HARD, EARLY_ROW.at), (Grade.AGAIN, LATE_ROW.at))
    assert [memories[direction] for direction in (T2H, V2H, V2T)] == [None, None, None]


def test_the_history_rows_are_left_exactly_as_they_were(tmp_path: Path) -> None:
    """Every `reviews` row, every column, the recorded word-level figures included: history
    is what was recorded then, never rewritten with the replayed values."""
    file = version_2_file(tmp_path)
    assert len(file.reviews_before) == 11  # sanity: 3 seeds and 8 answers

    file.migrated()

    assert all_rows(file.path, "reviews") == file.reviews_before


def test_the_old_memory_columns_on_words_are_left_as_they_were(tmp_path: Path) -> None:
    """They stay (SQLite cannot drop them past the CHECK without a rebuild) and the migration
    neither clears nor rewrites them."""
    file = version_2_file(tmp_path)

    file.migrated()

    assert all_rows(file.path, "words") == file.words_before


def test_the_old_memory_columns_are_never_read(tmp_path: Path) -> None:
    """A word whose old columns disagree with its history reads what its history replays to:
    the old figures are dead data. The word-level column is set to a `very_well` seed here."""
    path = file_at_version(tmp_path, 2)
    decoy, _ = seeded(Familiarity.VERY_WELL)
    with closing(sqlite3.connect(path)) as raw:
        word_id = write_word(raw, word(206), Familiarity.NEW, [ONE_DIRECTION_V2T])
        raw.execute(
            "UPDATE words SET stability = ?, difficulty = ?, next_review = ?, last_review = ?, "
            "review_count = ?, lapse_count = ? WHERE id = ?",
            (*memory_columns(decoy), word_id),
        )
        raw.commit()

    memories = memories_of(WordStore(Database(path)), word_id)

    assert memories[V2T] == replayed(None, (Grade.HARD, ONE_DIRECTION_V2T.at))
    assert [memories[direction] for direction in (H2T, T2H, V2H)] == [None, None, None]


def test_a_replay_that_fails_after_writing_leaves_the_file_at_version_2(tmp_path: Path) -> None:
    """The whole step ran, then the bump never happened: its table and rows are rolled back
    with it. Reopened with the real migrations, the file then upgrades as if nothing happened."""
    file = version_2_file(tmp_path)
    step = migration_3()

    def fails_after_the_replay(connection: sqlite3.Connection) -> None:
        step(connection)
        raise _Boom("simulated failure after the replay")

    failing = Database(file.path, migrations=(MIGRATIONS[0], MIGRATIONS[1], fails_after_the_replay))

    with pytest.raises(_Boom), failing.transaction():
        pass

    assert user_version(file.path) == 2
    assert "direction_memories" not in table_names(file.path)
    assert all_rows(file.path, "reviews") == file.reviews_before
    assert memories_of(file.migrated(), file.ids["well"]) == same_memory(
        seeded(Familiarity.WELL)[0]
    )


def test_a_replay_that_fails_halfway_leaves_no_memory_row_behind(tmp_path: Path) -> None:
    """A failure in the middle of the replay, on the first answered row it grades."""
    file = version_2_file(tmp_path)

    # The replay's own call into `srs/` is the only place to fail it from the middle.
    with (
        patch("oral_korean.storage.database.apply_grade", side_effect=_Boom("mid-replay")),
        pytest.raises(_Boom),
        Database(file.path).transaction(),
    ):
        pass

    assert user_version(file.path) == 2
    assert "direction_memories" not in table_names(file.path)
    assert all_rows(file.path, "reviews") == file.reviews_before


# ---------------------------------------------------------------------------------
# Python steps in the runner
# ---------------------------------------------------------------------------------


def test_a_python_step_runs_on_the_open_connection_inside_its_transaction(
    tmp_path: Path,
) -> None:
    """Called once, with a connection already in a transaction, and bumped with it."""
    path = tmp_path / "oral-korean.sqlite3"
    seen: list[bool] = []

    def python_step(connection: sqlite3.Connection) -> None:
        seen.append(connection.in_transaction)
        connection.execute("CREATE TABLE scratch_py (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO scratch_py (id) VALUES (7)")

    database = Database(path, migrations=("CREATE TABLE scratch_sql (id INTEGER);", python_step))

    with database.transaction() as conn:
        rows = conn.execute("SELECT id FROM scratch_py").fetchall()

    assert seen == [True]
    assert rows == [(7,)]
    assert user_version(path) == 2


def test_a_python_step_that_raises_leaves_its_writes_and_version_untouched(
    tmp_path: Path,
) -> None:
    """The SQL step before it stays applied; the Python step's table does not."""
    path = tmp_path / "oral-korean.sqlite3"

    def fails_halfway(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE scratch_py (id INTEGER PRIMARY KEY)")
        raise _Boom("simulated failure halfway through a Python step")

    database = Database(path, migrations=("CREATE TABLE scratch_sql (id INTEGER);", fails_halfway))

    with pytest.raises(_Boom), database.transaction():
        pass

    assert user_version(path) == 1
    assert "scratch_sql" in table_names(path)
    assert "scratch_py" not in table_names(path)


def test_a_python_step_already_applied_is_not_run_again(tmp_path: Path) -> None:
    """Reopening an up-to-date file calls no step: the replay must never run twice."""
    path = tmp_path / "oral-korean.sqlite3"
    calls: list[int] = []

    def counted(connection: sqlite3.Connection) -> None:
        calls.append(1)
        connection.execute("CREATE TABLE scratch_py (id INTEGER PRIMARY KEY)")

    for _ in range(2):
        with Database(path, migrations=(counted,)).transaction():
            pass

    assert calls == [1]


# ---------------------------------------------------------------------------------
# Migration 2, and a version-1 file coming through both
# ---------------------------------------------------------------------------------


def typed_right() -> AnswerContext:
    return AnswerContext(direction=T2H, mode=AnswerMode.TYPING, correct=True)


def test_a_version_1_file_upgrades_keeping_every_word_and_seed(tmp_path: Path) -> None:
    """The file vocab-core wrote: a new word and a seeded one, the seed row with a null answer
    context in migration 2's three columns, and the seed in every direction after migration 3.
    """
    path = file_at_version(tmp_path, 1)
    state, record = seeded(Familiarity.WELL)
    with closing(sqlite3.connect(path)) as raw:
        new_id = write_word(raw, word(80), Familiarity.NEW, tags=("food",))
        seeded_id = write_word(raw, word(81), Familiarity.WELL, tags=("fruit",))
        raw.commit()

    store = WordStore(Database(path))
    new_word, seeded_word = store.get_word(new_id), store.get_word(seeded_id)

    assert user_version(path) == len(MIGRATIONS)
    assert new_word is not None and seeded_word is not None
    assert (new_word.korean, new_word.tags, new_word.added_at) == (word(80), ("food",), T0)
    assert (seeded_word.korean, seeded_word.tags) == (word(81), ("fruit",))
    assert dict(new_word.memories) == same_memory(None)
    assert dict(seeded_word.memories) == same_memory(state)
    assert store.history(seeded_id) == (HistoryRow(record=record, answer=None),)
    assert not store.history(new_id)
    assert all_rows(path, "reviews")[0][-3:] == (None, None, None)


def test_an_upgraded_version_1_file_records_an_answer_after_its_seed(tmp_path: Path) -> None:
    """Usable, not merely readable: the answer lands in its direction, after the seed row."""
    path = file_at_version(tmp_path, 1)
    state, seed_record = seeded(Familiarity.WELL)
    with closing(sqlite3.connect(path)) as raw:
        word_id = write_word(raw, word(82), Familiarity.WELL)
        raw.commit()
    store = WordStore(Database(path))
    after, record = apply_grade(state, Grade.GOOD, state.next_review, fuzzing=False)

    assert store.record_answer(word_id, after, record, typed_right()) is True

    assert store.history(word_id) == (
        HistoryRow(record=seed_record, answer=None),
        HistoryRow(record=record, answer=typed_right()),
    )
    assert memories_of(store, word_id) == {H2T: state, T2H: after, V2H: state, V2T: state}
