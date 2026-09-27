"""Tests for what `vocab-sessions` T03 adds to `storage`: answered reviews, new and due words.

Split from `test_storage.py` (vocab-core T04's contract, whose history assertions T03 updates
and whose signature table pins the three new methods) only to keep both files under pylint's
module-length limit. Written before the implementation; the contract:

- **Migration 2**, appended to `database.MIGRATIONS`: nullable `direction TEXT`,
  `answer_mode TEXT` and `correct INTEGER` (0 or 1) columns on `reviews`, null on every row
  that existed before it (seeds). It is the first migration to run on the user's real data,
  so it is tested on a file written at version 1 by `Database(path, migrations=MIGRATIONS[:1])`
  and a `WordStore` over it.
- `words.AnswerContext` (frozen): `direction: Direction`, `mode: AnswerMode`, `correct: bool` -
  what an answered review adds to its history row.
- `words.HistoryRow` (frozen): `record: ReviewRecord`, `answer: AnswerContext | None` (`None`
  for a seed). `WordStore.history` returns these.
- `WordStore.record_answer(word_id, state, record, answer) -> bool`: the word's new memory state
  and its history row in one transaction; `False`, with nothing written, when the word no
  longer exists; any other failure raises (`sqlite3.Error`) and leaves neither written.
- `WordStore.new_words(*, tag=None, limit) -> tuple[VocabularyWord, ...]`: the words with no
  memory state, oldest first (`added_at`, then id), filtered by exact tag, capped.
- `WordStore.due_words(at, *, tag=None, limit) -> tuple[VocabularyWord, ...]`: the words whose
  next review is at or before `at`, most overdue first (next review, then id), filtered by
  exact tag, capped.

A failure half-way through `record_answer` is injected with a SQLite trigger created on the
test's own file (`RAISE(ABORT)` on one of the two writes), not by patching a private helper:
the trigger fails the real statement, whatever the implementation's helpers are called and
whichever write it makes first (both orders are covered).

Real SQLite files under `tmp_path`; memory states and records come from `srs/` with fuzzing
off, never built by hand.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from test_storage import T0, build_store, seed_pair, word

from oral_korean.exercises.vocab import AnswerMode, Direction
from oral_korean.exercises.vocab_words import make_draft
from oral_korean.srs.memory import Familiarity, Grade, apply_grade
from oral_korean.storage.database import MIGRATIONS, Database
from oral_korean.storage.words import AnswerContext, HistoryRow, WordStore


def typed_right() -> AnswerContext:
    """An answer context for a right typed answer, when which one does not matter."""
    return AnswerContext(
        direction=Direction.TRANSLATION_TO_HANGUL, mode=AnswerMode.TYPING, correct=True
    )


# ---------------------------------------------------------------------------------
# Migration 2: the answer context on history rows
# ---------------------------------------------------------------------------------


def test_the_answer_context_values_are_frozen_with_their_agreed_fields() -> None:
    """T03's routes read these by name; a mutable history row could drift from the file."""
    context = AnswerContext(
        direction=Direction.VOICE_TO_HANGUL, mode=AnswerMode.CHOICE, correct=True
    )
    _, record = seed_pair(Familiarity.WELL)
    row = HistoryRow(record=record, answer=context)

    assert [field.name for field in dataclasses.fields(context)] == [
        "direction",
        "mode",
        "correct",
    ]
    assert [field.name for field in dataclasses.fields(row)] == ["record", "answer"]
    for value, name in [(context, "correct"), (row, "answer")]:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, name, None)


def test_migration_2_upgrades_a_version_1_file_keeping_every_word_state_and_seed(
    tmp_path: Path,
) -> None:
    """The user's real file is at version 1: two words written at version 1, one new and one
    seeded, must come through the upgrade exactly, the seed row with a null answer context
    in all three new columns.
    """
    path = tmp_path / "oral-korean.sqlite3"
    version_1 = Database(path, migrations=MIGRATIONS[:1])
    state, record = seed_pair(Familiarity.WELL)
    new_draft = make_draft(word(80), "apple", ["food"], Familiarity.NEW)
    seeded_draft = make_draft(word(81), "pear", ["fruit"], Familiarity.WELL)
    before = WordStore(version_1).add_words(
        [(new_draft, None), (seeded_draft, (state, record))], T0
    )
    with version_1.transaction() as conn:
        version_before = conn.execute("PRAGMA user_version").fetchone()[0]

    upgraded = Database(path)
    store = WordStore(upgraded)
    words_after = store.list_words()
    with upgraded.transaction() as conn:
        version_after = conn.execute("PRAGMA user_version").fetchone()[0]
        answer_columns = conn.execute(
            "SELECT direction, answer_mode, correct FROM reviews"
        ).fetchall()

    assert version_before == 1
    assert len(MIGRATIONS) >= 2
    assert version_after == len(MIGRATIONS)
    assert words_after == before
    assert words_after[0].memory is None
    assert words_after[1].memory == state
    assert store.history(before[1].id) == (HistoryRow(record=record, answer=None),)
    assert not store.history(before[0].id)
    assert answer_columns == [(None, None, None)]


def test_a_migrated_file_records_an_answer_after_its_seed(tmp_path: Path) -> None:
    """The upgraded file is usable, not merely readable: the seeded word takes an answer."""
    path = tmp_path / "oral-korean.sqlite3"
    state, seed_record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(82), "pear", [], Familiarity.WELL)
    (added,) = WordStore(Database(path, migrations=MIGRATIONS[:1])).add_words(
        [(draft, (state, seed_record))], T0
    )
    store = WordStore(Database(path))
    after, record = apply_grade(state, Grade.GOOD, state.next_review, fuzzing=False)

    assert store.record_answer(added.id, after, record, typed_right()) is True

    assert store.history(added.id) == (
        HistoryRow(record=seed_record, answer=None),
        HistoryRow(record=record, answer=typed_right()),
    )


# ---------------------------------------------------------------------------------
# Recording an answered review
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "mode", "correct"),
    [
        pytest.param(
            Direction.HANGUL_TO_TRANSLATION, AnswerMode.CHOICE, True, id="hangul-choice-right"
        ),
        pytest.param(
            Direction.TRANSLATION_TO_HANGUL,
            AnswerMode.TYPING,
            False,
            id="translation-typing-wrong",
        ),
        pytest.param(
            Direction.VOICE_TO_HANGUL, AnswerMode.TYPING, True, id="voice-hangul-typing-right"
        ),
        pytest.param(
            Direction.VOICE_TO_TRANSLATION,
            AnswerMode.CHOICE,
            False,
            id="voice-translation-choice-wrong",
        ),
    ],
)
def test_recording_an_answer_writes_the_state_and_the_history_row(
    tmp_path: Path, direction: Direction, mode: AnswerMode, correct: bool
) -> None:
    """Every direction and both modes, right and wrong, read back as they were recorded."""
    store = build_store(tmp_path)
    (added,) = store.add_words([(make_draft(word(83), "a", [], Familiarity.NEW), None)], T0)
    grade = Grade.HARD if correct else Grade.AGAIN
    state, record = apply_grade(None, grade, T0 + timedelta(hours=1), fuzzing=False)
    context = AnswerContext(direction=direction, mode=mode, correct=correct)

    result = store.record_answer(added.id, state, record, context)

    assert result is True
    fetched = store.get_word(added.id)
    assert fetched is not None
    assert fetched.memory == state
    assert store.history(added.id) == (HistoryRow(record=record, answer=context),)


def test_an_answer_after_a_seed_is_listed_after_it(tmp_path: Path) -> None:
    """Chronological over two rows at last: the seed, then the answer a week later."""
    store = build_store(tmp_path)
    seeded_state, seed_record = seed_pair(Familiarity.A_LITTLE)
    draft = make_draft(word(84), "a", [], Familiarity.A_LITTLE)
    (added,) = store.add_words([(draft, (seeded_state, seed_record))], T0)
    state, record = apply_grade(
        seeded_state, Grade.AGAIN, T0 + timedelta(days=7), fuzzing=False
    )
    context = AnswerContext(
        direction=Direction.VOICE_TO_TRANSLATION, mode=AnswerMode.CHOICE, correct=False
    )

    store.record_answer(added.id, state, record, context)

    assert store.history(added.id) == (
        HistoryRow(record=seed_record, answer=None),
        HistoryRow(record=record, answer=context),
    )
    fetched = store.get_word(added.id)
    assert fetched is not None
    assert fetched.memory == state


def test_recording_an_answer_for_a_deleted_word_reports_it_missing_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """A word deleted while its question was pending: `False`, never an error, no orphan row."""
    path = tmp_path / "oral-korean.sqlite3"
    store = WordStore(Database(path))
    (added,) = store.add_words([(make_draft(word(85), "a", [], Familiarity.NEW), None)], T0)
    assert store.delete_word(added.id) is True
    state, record = apply_grade(None, Grade.HARD, T0, fuzzing=False)

    result = store.record_answer(added.id, state, record, typed_right())

    assert result is False
    assert store.get_word(added.id) is None
    with Database(path).transaction() as conn:
        review_rows = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        word_rows = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    assert (review_rows, word_rows) == (0, 0)


def test_recording_an_answer_for_an_id_never_stored_reports_it_missing(tmp_path: Path) -> None:
    """The same `False` for an id nothing ever had."""
    store = build_store(tmp_path)
    state, record = apply_grade(None, Grade.HARD, T0, fuzzing=False)

    assert store.record_answer(999, state, record, typed_right()) is False
    assert not store.history(999)


@pytest.mark.parametrize(
    "trigger",
    [
        pytest.param(
            "CREATE TRIGGER injected_failure BEFORE INSERT ON reviews "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
            id="history-row-write-fails",
        ),
        pytest.param(
            "CREATE TRIGGER injected_failure BEFORE UPDATE ON words "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
            id="memory-state-write-fails",
        ),
    ],
)
def test_a_failure_half_way_through_recording_leaves_neither_write(
    tmp_path: Path, trigger: str
) -> None:
    """Whichever of the two writes fails, the other is rolled back with it, and the failure
    is raised rather than reported as a missing word. A trigger fails the real statement, so
    the test holds whatever order the implementation writes in.
    """
    database = Database(tmp_path / "oral-korean.sqlite3")
    store = WordStore(database)
    seeded_state, seed_record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(86), "a", [], Familiarity.WELL)
    (added,) = store.add_words([(draft, (seeded_state, seed_record))], T0)
    with database.transaction() as conn:
        conn.execute(trigger)
    state, record = apply_grade(
        seeded_state, Grade.GOOD, seeded_state.next_review, fuzzing=False
    )

    with pytest.raises(sqlite3.Error):
        store.record_answer(added.id, state, record, typed_right())

    fetched = store.get_word(added.id)
    assert fetched is not None
    assert fetched.memory == seeded_state
    assert store.history(added.id) == (HistoryRow(record=seed_record, answer=None),)


# ---------------------------------------------------------------------------------
# New words
# ---------------------------------------------------------------------------------


def test_new_words_are_the_words_with_no_memory_oldest_first(tmp_path: Path) -> None:
    """A word stored first but added at a later instant sorts by its instant, not its id;
    a seeded word is never new.
    """
    store = build_store(tmp_path)
    (later,) = store.add_words(
        [(make_draft(word(90), "later", [], Familiarity.NEW), None)], T0 + timedelta(hours=1)
    )
    earlier_a, seeded_word, earlier_b = store.add_words(
        [
            (make_draft(word(91), "earlier a", [], Familiarity.NEW), None),
            (make_draft(word(92), "seeded", [], Familiarity.WELL), seed_pair(Familiarity.WELL)),
            (make_draft(word(93), "earlier b", [], Familiarity.NEW), None),
        ],
        T0,
    )

    new = store.new_words(limit=10)

    assert new == (earlier_a, earlier_b, later)
    assert seeded_word not in new


def test_new_words_are_filtered_by_exact_tag(tmp_path: Path) -> None:
    """Only the tag given, matched exactly as `list_words` matches it."""
    store = build_store(tmp_path)
    food, _, food_too = store.add_words(
        [
            (make_draft(word(94), "apple", ["food"], Familiarity.NEW), None),
            (make_draft(word(95), "run", ["verb"], Familiarity.NEW), None),
            (make_draft(word(96), "pear", ["food", "fruit"], Familiarity.NEW), None),
        ],
        T0,
    )

    assert store.new_words(tag="food", limit=10) == (food, food_too)
    assert not store.new_words(tag="Food", limit=10)
    assert not store.new_words(tag="nonexistent", limit=10)


def test_new_words_are_capped_at_the_limit_keeping_the_oldest(tmp_path: Path) -> None:
    """Three new words, a limit of two: the first two added."""
    store = build_store(tmp_path)
    added = store.add_words(
        [(make_draft(word(97 + n), f"w{n}", [], Familiarity.NEW), None) for n in range(3)], T0
    )

    assert store.new_words(limit=2) == added[:2]


def test_new_words_of_an_empty_store_are_empty(tmp_path: Path) -> None:
    """Nothing to learn is an empty tuple, which the route turns into its 409."""
    store = build_store(tmp_path)

    assert not store.new_words(limit=5)


# ---------------------------------------------------------------------------------
# Due words
# ---------------------------------------------------------------------------------


def test_due_words_are_the_words_due_by_the_instant_most_overdue_first(
    tmp_path: Path,
) -> None:
    """`a_little` falls due a day after its seed and `well` two days after; `very_well` is
    not due yet and a new word is never due. At the `well` word's exact due instant both
    seeded ones are due (at or before), the `a_little` ones first, their tie broken by id.
    """
    store = build_store(tmp_path)
    well_state, well_record = seed_pair(Familiarity.WELL)
    little_state, little_record = seed_pair(Familiarity.A_LITTLE)
    well, little, _, _, little_twin = store.add_words(
        [
            (make_draft(word(100), "well", [], Familiarity.WELL), (well_state, well_record)),
            (
                make_draft(word(101), "little", [], Familiarity.A_LITTLE),
                (little_state, little_record),
            ),
            (
                make_draft(word(102), "very well", [], Familiarity.VERY_WELL),
                seed_pair(Familiarity.VERY_WELL),
            ),
            (make_draft(word(103), "new", [], Familiarity.NEW), None),
            (
                make_draft(word(104), "little twin", [], Familiarity.A_LITTLE),
                (little_state, little_record),
            ),
        ],
        T0,
    )
    assert little_state.next_review < well_state.next_review  # sanity on the seeds

    due = store.due_words(well_state.next_review, limit=10)

    assert due == (little, little_twin, well)
    assert not store.due_words(T0, limit=10)


@pytest.mark.parametrize(
    ("offset", "expected_due"),
    [
        pytest.param(timedelta(0), False, id="at-the-whole-second-before-it"),
        pytest.param(timedelta(microseconds=500_000), True, id="exactly-at-it"),
        pytest.param(timedelta(seconds=1), True, id="at-the-next-whole-second"),
    ],
)
def test_a_word_due_half_way_through_a_second_is_due_from_that_microsecond(
    tmp_path: Path, offset: timedelta, expected_due: bool
) -> None:
    """Seeded at 09:00:00.500000, it falls due at 09:00:00.500000 a day later: not at
    09:00:00, but at that instant and at 09:00:01. Catches a comparison that drops
    microseconds, or compares texts written in two different formats.
    """
    store = build_store(tmp_path)
    at = T0.replace(microsecond=500_000)
    state, record = seed_pair(Familiarity.A_LITTLE, at)
    draft = make_draft(word(105), "a", [], Familiarity.A_LITTLE)
    (added,) = store.add_words([(draft, (state, record))], at)
    assert state.next_review.microsecond == 500_000  # sanity: the seed kept the half second
    whole_second = state.next_review.replace(microsecond=0)

    due = store.due_words(whole_second + offset, limit=10)

    assert due == ((added,) if expected_due else ())


def test_due_words_are_filtered_by_exact_tag_and_capped(tmp_path: Path) -> None:
    """The tag narrows before the cap, and the cap keeps the most overdue."""
    store = build_store(tmp_path)
    earlier = seed_pair(Familiarity.A_LITTLE, T0)
    later = seed_pair(Familiarity.A_LITTLE, T0 + timedelta(hours=1))
    (untagged,) = store.add_words(
        [(make_draft(word(106), "untagged", [], Familiarity.A_LITTLE), earlier)], T0
    )
    (food_later,) = store.add_words(
        [(make_draft(word(107), "food later", ["food"], Familiarity.A_LITTLE), later)],
        T0 + timedelta(hours=1),
    )
    (food_earlier,) = store.add_words(
        [(make_draft(word(108), "food earlier", ["food"], Familiarity.A_LITTLE), earlier)], T0
    )
    at = T0 + timedelta(days=3)

    assert store.due_words(at, tag="food", limit=10) == (food_earlier, food_later)
    assert store.due_words(at, tag="food", limit=1) == (food_earlier,)
    assert store.due_words(at, limit=1) == (untagged,)
    assert not store.due_words(at, tag="Food", limit=10)
