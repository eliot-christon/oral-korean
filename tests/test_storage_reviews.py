"""Tests for what `vocab-sessions` T03 adds to `storage`: answered reviews, new and due words.

Split from `test_storage.py` (vocab-core T04's contract, whose history assertions T03 updates
and whose signature table pins the three new methods) only to keep both files under pylint's
module-length limit. Written before the implementation; the contract:

- **Migration 2**, appended to `database.MIGRATIONS`: nullable `direction TEXT`,
  `answer_mode TEXT` and `correct INTEGER` (0 or 1) columns on `reviews`, null on every row
  that existed before it (seeds). Tested in `test_storage_migration.py`.
- `words.AnswerContext` (frozen): `direction: Direction`, `mode: AnswerMode`, `correct: bool` -
  what an answered review adds to its history row.
- `words.HistoryRow` (frozen): `record: ReviewRecord`, `answer: AnswerContext | None` (`None`
  for a seed). `WordStore.history` returns these.

vocab-directions T01 gives each word one memory per direction (`VocabularyWord.memories`, rows
of `direction_memories`, one per direction that has a memory), and:

- `add_words`: a seeded entry gives all four directions the seed state, and writes **one** seed
  row, with a null direction.
- `WordStore.record_answer(word_id, state, record, answer) -> bool`: `state` becomes the memory
  of `answer.direction` **only**, written with its history row in one transaction; `False`,
  with nothing written, when the word no longer exists; any other failure raises
  (`sqlite3.Error`) and leaves neither written.
- `WordStore.new_words(*, tag=None, directions=tuple(Direction), limit)`: the words with at
  least one direction among `directions` that has no memory, oldest first (`added_at`, then
  id), filtered by exact tag, capped.
- `WordStore.due_words(at, *, tag=None, directions=tuple(Direction), limit)`: the words with at
  least one direction among `directions` whose memory is due at `at` (`next_review <= at`),
  ordered by the earliest such due instant, then id, filtered by exact tag, capped.
- The six word-level memory columns migration 1 put on `words` are never written again.

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
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_storage import T0, build_store, seed_pair, word

from oral_korean.exercises.vocab import AnswerMode, Direction
from oral_korean.exercises.vocab_words import VocabularyWord, make_draft, same_memory
from oral_korean.srs.memory import Familiarity, Grade, MemoryState, apply_grade
from oral_korean.storage.database import Database
from oral_korean.storage.words import AnswerContext, HistoryRow, WordStore

type _Row = tuple[Any, ...]

H2T = Direction.HANGUL_TO_TRANSLATION
T2H = Direction.TRANSLATION_TO_HANGUL
V2H = Direction.VOICE_TO_HANGUL
V2T = Direction.VOICE_TO_TRANSLATION


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


# Migration 2's own tests moved to `test_storage_migration.py` with vocab-directions T01: they
# wrote a version-1 file through `WordStore`, which now writes a table version 1 does not have.


# ---------------------------------------------------------------------------------
# Adding a seeded word: every direction, one seed row
# ---------------------------------------------------------------------------------


def memory_rows(path: Path, word_id: int) -> list[_Row]:
    """A word's `direction_memories` rows, the direction first, in direction order."""
    with closing(sqlite3.connect(path)) as raw:
        rows: list[_Row] = raw.execute(
            "SELECT direction, stability, difficulty, next_review, last_review, review_count, "
            "lapse_count FROM direction_memories WHERE word_id = ? ORDER BY direction",
            (word_id,),
        ).fetchall()
    return rows


def old_memory_columns(path: Path, word_id: int) -> _Row:
    """The six word-level memory columns migration 1 created, which nothing writes any more."""
    with closing(sqlite3.connect(path)) as raw:
        row: _Row = raw.execute(
            "SELECT stability, difficulty, next_review, last_review, review_count, lapse_count "
            "FROM words WHERE id = ?",
            (word_id,),
        ).fetchone()
    return row


def test_a_word_seeded_very_well_has_the_seed_in_all_four_directions_and_one_seed_row(
    tmp_path: Path,
) -> None:
    """The seed is knowledge the user brought, the same whichever way the word is asked; the
    history says it once, with no direction, meaning all of them."""
    path = tmp_path / "oral-korean.sqlite3"
    store = WordStore(Database(path))
    state, record = seed_pair(Familiarity.VERY_WELL)
    draft = make_draft(word(87), "a", [], Familiarity.VERY_WELL)

    (added,) = store.add_words([(draft, (state, record))], T0)

    assert dict(added.memories) == same_memory(state)
    assert store.get_word(added.id) == added
    assert store.history(added.id) == (HistoryRow(record=record, answer=None),)
    with closing(sqlite3.connect(path)) as raw:
        directions = raw.execute(
            "SELECT direction FROM reviews WHERE word_id = ?", (added.id,)
        ).fetchall()
    assert directions == [(None,)]
    assert len(memory_rows(path, added.id)) == 4


def test_a_new_word_has_no_memory_row_and_nothing_in_the_old_columns(tmp_path: Path) -> None:
    """A direction without memory has no row; the retired word-level columns stay null."""
    path = tmp_path / "oral-korean.sqlite3"
    store = WordStore(Database(path))

    (added,) = store.add_words([(make_draft(word(88), "a", [], Familiarity.NEW), None)], T0)

    assert dict(added.memories) == same_memory(None)
    assert not memory_rows(path, added.id)
    assert old_memory_columns(path, added.id) == (None,) * 6


def test_seeding_and_answering_never_write_the_old_word_level_columns(tmp_path: Path) -> None:
    """From migration 3 on, the six columns on `words` are dead: neither a seed nor an answer
    writes them, so nothing can come to read a stale figure from them."""
    path = tmp_path / "oral-korean.sqlite3"
    store = WordStore(Database(path))
    seeded_state, seed_record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(89), "a", [], Familiarity.WELL)
    (added,) = store.add_words([(draft, (seeded_state, seed_record))], T0)
    state, record = apply_grade(
        seeded_state, Grade.GOOD, seeded_state.next_review, fuzzing=False
    )

    store.record_answer(added.id, state, record, typed_right())

    assert old_memory_columns(path, added.id) == (None,) * 6


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
    """Every direction and both modes, right and wrong, read back as they were recorded: the
    state lands in the direction answered, and a new word's other three stay without memory."""
    store = build_store(tmp_path)
    (added,) = store.add_words([(make_draft(word(83), "a", [], Familiarity.NEW), None)], T0)
    grade = Grade.HARD if correct else Grade.AGAIN
    state, record = apply_grade(None, grade, T0 + timedelta(hours=1), fuzzing=False)
    context = AnswerContext(direction=direction, mode=mode, correct=correct)

    result = store.record_answer(added.id, state, record, context)

    assert result is True
    fetched = store.get_word(added.id)
    assert fetched is not None
    assert dict(fetched.memories) == {**same_memory(None), direction: state}
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
    assert dict(fetched.memories) == {**same_memory(seeded_state), V2T: state}


@pytest.mark.parametrize("answered", list(Direction), ids=[d.value for d in Direction])
def test_an_answer_changes_its_direction_and_leaves_the_other_three_byte_identical(
    tmp_path: Path, answered: Direction
) -> None:
    """Seeded `well`, answered good on its due date in one direction: that memory moves, and
    the other three rows are untouched to the byte, not merely equal once read back."""
    path = tmp_path / "oral-korean.sqlite3"
    store = WordStore(Database(path))
    seeded_state, seed_record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(109), "a", [], Familiarity.WELL)
    (added,) = store.add_words([(draft, (seeded_state, seed_record))], T0)
    others_before = [row for row in memory_rows(path, added.id) if row[0] != answered.value]
    state, record = apply_grade(
        seeded_state, Grade.GOOD, seeded_state.next_review, fuzzing=False
    )
    context = AnswerContext(direction=answered, mode=AnswerMode.TYPING, correct=True)

    assert store.record_answer(added.id, state, record, context) is True

    fetched = store.get_word(added.id)
    assert fetched is not None
    assert fetched.memories[answered] == state != seeded_state
    assert {d: m for d, m in fetched.memories.items() if d is not answered} == {
        d: seeded_state for d in Direction if d is not answered
    }
    others_after = [row for row in memory_rows(path, added.id) if row[0] != answered.value]
    assert len(others_before) == 3
    assert others_after == others_before


def test_answers_in_two_directions_build_two_independent_memories(tmp_path: Path) -> None:
    """A new word, right in one direction and wrong in another: each memory is its own
    history, and neither answer reaches the direction it was not asked in."""
    store = build_store(tmp_path)
    (added,) = store.add_words([(make_draft(word(110), "a", [], Familiarity.NEW), None)], T0)
    right, right_record = apply_grade(None, Grade.HARD, T0, fuzzing=False)
    wrong, wrong_record = apply_grade(None, Grade.AGAIN, T0 + timedelta(hours=1), fuzzing=False)

    store.record_answer(
        added.id, right, right_record, AnswerContext(H2T, AnswerMode.CHOICE, correct=True)
    )
    store.record_answer(
        added.id, wrong, wrong_record, AnswerContext(V2H, AnswerMode.CHOICE, correct=False)
    )

    fetched = store.get_word(added.id)
    assert fetched is not None
    assert dict(fetched.memories) == {H2T: right, T2H: None, V2H: wrong, V2T: None}


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


def failing_trigger(name: str, event: str) -> str:
    """A trigger that aborts every `event` (`INSERT ON reviews`, ...) with an injected error."""
    return (
        f"CREATE TRIGGER {name} BEFORE {event} "
        "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )


@pytest.mark.parametrize(
    "triggers",
    [
        pytest.param(
            [failing_trigger("no_review", "INSERT ON reviews")], id="history-row-write-fails"
        ),
        pytest.param(
            [
                failing_trigger("no_memory_insert", "INSERT ON direction_memories"),
                failing_trigger("no_memory_update", "UPDATE ON direction_memories"),
            ],
            id="memory-state-write-fails",
        ),
    ],
)
def test_a_failure_half_way_through_recording_leaves_neither_write(
    tmp_path: Path, triggers: list[str]
) -> None:
    """Whichever of the two writes fails, the other is rolled back with it, and the failure
    is raised rather than reported as a missing word. A trigger fails the real statement, so
    the test holds whatever order the implementation writes in, and whether it updates the
    direction's row or replaces it.
    """
    database = Database(tmp_path / "oral-korean.sqlite3")
    store = WordStore(database)
    seeded_state, seed_record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(86), "a", [], Familiarity.WELL)
    (added,) = store.add_words([(draft, (seeded_state, seed_record))], T0)
    with database.transaction() as conn:
        for trigger in triggers:
            conn.execute(trigger)
    state, record = apply_grade(
        seeded_state, Grade.GOOD, seeded_state.next_review, fuzzing=False
    )

    with pytest.raises(sqlite3.Error):
        store.record_answer(added.id, state, record, typed_right())

    fetched = store.get_word(added.id)
    assert fetched is not None
    assert dict(fetched.memories) == same_memory(seeded_state)
    assert store.history(added.id) == (HistoryRow(record=seed_record, answer=None),)


# ---------------------------------------------------------------------------------
# New words
# ---------------------------------------------------------------------------------


def test_new_words_are_the_words_with_no_memory_in_learn_queue_order(tmp_path: Path) -> None:
    """A word joins the learn queue when it is stored, whatever instant it is added at
    (vocab-directions T03; before it, new words sorted by that instant); a seeded word is
    never new.
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

    assert new == (later, earlier_a, earlier_b)
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


# ---------------------------------------------------------------------------------
# The pools, per direction (vocab-directions T01)
# ---------------------------------------------------------------------------------


def answer_in(
    store: WordStore, word_id: int, direction: Direction, grade: Grade, at: datetime
) -> MemoryState:
    """Answer the stored word in `direction` at `at`, graded `grade`; its new state there."""
    found = store.get_word(word_id)
    assert found is not None
    state, record = apply_grade(found.memories[direction], grade, at, fuzzing=False)
    context = AnswerContext(direction, AnswerMode.CHOICE, correct=grade is not Grade.AGAIN)
    assert store.record_answer(word_id, state, record, context) is True
    return state


def new_word_answered_in(
    store: WordStore, number: int, directions: tuple[Direction, ...]
) -> VocabularyWord:
    """A word added new at T0, then answered right by choice at T0 in each of `directions`."""
    (added,) = store.add_words(
        [(make_draft(word(number), f"w{number}", [], Familiarity.NEW), None)], T0
    )
    for direction in directions:
        answer_in(store, added.id, direction, Grade.HARD, T0)
    return added


def ids(words: tuple[VocabularyWord, ...]) -> list[int]:
    return [found.id for found in words]


def test_new_words_are_the_words_missing_a_memory_in_a_ticked_direction(
    tmp_path: Path,
) -> None:
    """Ticking hangul-to-translation alone: a word learned in every other direction is still
    to learn, one learned in all four is not, and nor is one learned in that direction only,
    however much it lacks elsewhere. With every direction ticked, anything missing one is new.
    """
    store = build_store(tmp_path)
    all_but_h2t = new_word_answered_in(store, 120, (T2H, V2H, V2T))
    all_four = new_word_answered_in(store, 121, (H2T, T2H, V2H, V2T))
    only_h2t = new_word_answered_in(store, 122, (H2T,))
    never = new_word_answered_in(store, 123, ())

    assert ids(store.new_words(directions={H2T}, limit=10)) == [all_but_h2t.id, never.id]
    assert ids(store.new_words(limit=10)) == [all_but_h2t.id, only_h2t.id, never.id]
    assert all_four.id not in ids(store.new_words(limit=10))


def test_new_words_read_back_with_every_direction_as_stored(tmp_path: Path) -> None:
    """The pool returns whole words, their learned directions included, not the missing ones
    alone: the session scores against these memories."""
    store = build_store(tmp_path)
    partly = new_word_answered_in(store, 124, (V2T,))

    (found,) = store.new_words(directions={H2T}, limit=10)

    assert found == store.get_word(partly.id)
    assert found.memories[V2T] is not None


def test_due_words_are_the_words_with_a_ticked_direction_due(tmp_path: Path) -> None:
    """Seeded `a_little` (all four due a day later), then three directions answered on that
    day: only voice-to-Hangul is still due, so the word is due when it is ticked, and not when
    only the other three are."""
    store = build_store(tmp_path)
    draft = make_draft(word(125), "a", [], Familiarity.A_LITTLE)
    (added,) = store.add_words([(draft, seed_pair(Familiarity.A_LITTLE))], T0)
    day = T0 + timedelta(days=1)
    moved = [answer_in(store, added.id, d, Grade.GOOD, day) for d in (H2T, T2H, V2T)]
    at = day + timedelta(hours=1)
    assert all(state.next_review > at for state in moved)  # sanity: the three moved out

    assert ids(store.due_words(at, directions={V2H}, limit=10)) == [added.id]
    assert not store.due_words(at, directions={H2T, T2H, V2T}, limit=10)
    assert ids(store.due_words(at, limit=10)) == [added.id]


def test_a_direction_without_memory_is_never_due(tmp_path: Path) -> None:
    """Learned in one direction and due there: never due through the three it lacks."""
    store = build_store(tmp_path)
    partly = new_word_answered_in(store, 126, (H2T,))
    at = T0 + timedelta(days=30)

    assert ids(store.due_words(at, directions={H2T}, limit=10)) == [partly.id]
    assert not store.due_words(at, directions={T2H, V2H, V2T}, limit=10)


def test_a_word_partly_learned_is_in_both_pools(tmp_path: Path) -> None:
    """Learned one way and due there, never asked the other three ways: reviewed in the
    first, learned in the others. Each pool reads only the directions ticked."""
    store = build_store(tmp_path)
    partly = new_word_answered_in(store, 127, (H2T,))
    at = T0 + timedelta(days=1)

    assert ids(store.new_words(directions={T2H}, limit=10)) == [partly.id]
    assert ids(store.due_words(at, directions={H2T}, limit=10)) == [partly.id]
    assert not store.new_words(directions={H2T}, limit=10)
    assert not store.due_words(at, directions={T2H}, limit=10)


def test_due_words_are_ordered_by_their_earliest_ticked_due_direction(tmp_path: Path) -> None:
    """`later` is seeded `a_little` (all due a day after T0) and missed in translation-to-Hangul
    an hour into that day, which brings that direction back a day on, after `well`'s two-day
    seed. Ticking translation-to-Hangul alone, `well` comes first; ticking anything that
    includes one of `later`'s untouched directions, `later` does: its own earliest due
    direction outside the ticked ones never counts.
    """
    store = build_store(tmp_path)
    well_state, well_record = seed_pair(Familiarity.WELL)
    well, later = store.add_words(
        [
            (make_draft(word(128), "well", [], Familiarity.WELL), (well_state, well_record)),
            (
                make_draft(word(129), "later", [], Familiarity.A_LITTLE),
                seed_pair(Familiarity.A_LITTLE),
            ),
        ],
        T0,
    )
    missed = answer_in(
        store, later.id, T2H, Grade.AGAIN, T0 + timedelta(days=1, hours=1)
    )
    assert well_state.next_review < missed.next_review  # sanity on the two dates
    at = T0 + timedelta(days=3)

    assert ids(store.due_words(at, directions={T2H}, limit=10)) == [well.id, later.id]
    assert ids(store.due_words(at, directions={T2H}, limit=1)) == [well.id]
    assert ids(store.due_words(at, directions={H2T}, limit=10)) == [later.id, well.id]
    assert ids(store.due_words(at, limit=10)) == [later.id, well.id]
