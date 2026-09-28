"""Tests for the stored learn queue and the review candidates: vocab-directions T03.

Written before the implementation, in their own file for pylint's module length
(`test_storage.py` is close to it). The contract:

- **Migration 4** adds `learn_queue`, one row per word with its position, filled in today's
  learn order (`added_at, id`). It only adds: no row or column of an existing table changes.
- `WordStore.learn_queue(*, tag=None, directions=all four)`: the words with at least one of
  `directions` without memory, in queue order, optionally carrying `tag`. A word added later
  goes last, and a batch keeps its order.
- `WordStore.reorder_learn_queue(word_ids)`: those words go to the top, in that order; every
  other word keeps its relative order after them. `QueueOrderError` (a `ValueError`) for an
  unknown id, a repeated id, or a word learned in every direction, with nothing changed.
- `new_words` follows the queue order.
- `WordStore.review_candidates(*, tag=None, directions=all four)`: the words with a learned
  direction among `directions`, by the earliest such next review, so at any instant the due
  ones come first (most overdue first), then the rest (soonest first).
- `WordStore.get_words(ids)`: the words with these ids, in that order, unknown ids skipped.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from test_storage import T0, build_store, seed_pair, word

from oral_korean.exercises.vocab import AnswerMode, Direction
from oral_korean.exercises.vocab_words import VocabularyWord, make_draft
from oral_korean.korean import hangul
from oral_korean.srs.memory import Familiarity, Grade, apply_grade
from oral_korean.storage.database import MIGRATIONS, Database
from oral_korean.storage.words import AnswerContext, QueueOrderError, WordStore

DAY = timedelta(days=1)


def add(
    store: WordStore,
    n: int,
    *,
    familiarity: Familiarity = Familiarity.NEW,
    tags: tuple[str, ...] = (),
) -> int:
    """Add word `n`, seeded for `familiarity`; its id."""
    draft = make_draft(word(n), f"meaning {n}", tags, familiarity)
    seeded = None if familiarity is Familiarity.NEW else seed_pair(familiarity)
    (added,) = store.add_words([(draft, seeded)], T0)
    return added.id


def answer(store: WordStore, word_id: int, direction: Direction, *, days: int = 0) -> None:
    """Answer `word_id` right in `direction`, from no memory, `days` after T0."""
    at = T0 + days * DAY
    state, record = apply_grade(None, Grade.HARD, at, fuzzing=False)
    context = AnswerContext(direction=direction, mode=AnswerMode.CHOICE, correct=True)
    assert store.record_answer(word_id, state, record, context)


def ids(words: Sequence[VocabularyWord]) -> list[int]:
    return [entry.id for entry in words]


# ---------------------------------------------------------------------------------
# Migration 4
# ---------------------------------------------------------------------------------


def test_the_migration_queues_existing_words_in_the_order_they_were_learned(
    tmp_path: Path,
) -> None:
    """A file at T01's version, words added A, B, C (C inserted first but added last)."""
    path = tmp_path / "oral-korean.sqlite3"
    with Database(path, migrations=MIGRATIONS[:3]).transaction() as connection:
        for n, added_at in ((3, T0 + 2 * DAY), (1, T0), (2, T0 + DAY)):
            connection.execute(
                "INSERT INTO words (korean, match_key, translations, familiarity, added_at) "
                "VALUES (?, ?, '[\"x\"]', 'new', ?)",
                (word(n), hangul.match_key(word(n)), added_at.isoformat(timespec="microseconds")),
            )
    store = WordStore(Database(path))

    assert [entry.korean for entry in store.learn_queue()] == [word(1), word(2), word(3)]


def test_the_migration_only_adds_a_table(tmp_path: Path) -> None:
    path = tmp_path / "oral-korean.sqlite3"
    with Database(path, migrations=MIGRATIONS[:3]).transaction():
        pass
    with closing(sqlite3.connect(path)) as raw:
        before = raw.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    WordStore(Database(path)).learn_queue()
    with closing(sqlite3.connect(path)) as raw:
        after = raw.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
        version = raw.execute("PRAGMA user_version").fetchone()[0]

    assert version == len(MIGRATIONS) == 4
    assert set(before) < set(after)
    assert {name for name, _ in set(after) - set(before)} >= {"learn_queue"}


# ---------------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------------


def test_the_queue_starts_in_the_order_the_words_were_added(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b, c = add(store, 1), add(store, 2), add(store, 3)

    assert ids(store.learn_queue()) == [a, b, c]


def test_reordering_puts_the_given_words_on_top_and_keeps_the_rest_in_order(
    tmp_path: Path,
) -> None:
    store = build_store(tmp_path)
    a, b, c = add(store, 1), add(store, 2), add(store, 3)

    store.reorder_learn_queue([c])
    assert ids(store.learn_queue()) == [c, a, b]

    store.reorder_learn_queue([b, c])
    assert ids(store.learn_queue()) == [b, c, a]


def test_a_word_added_after_a_reorder_goes_last(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b = add(store, 1), add(store, 2)
    store.reorder_learn_queue([b])
    c = add(store, 3)

    assert ids(store.learn_queue()) == [b, a, c]


def test_a_batch_joins_the_queue_in_its_own_order(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    drafts = [
        (make_draft(word(n), f"meaning {n}", (), Familiarity.NEW), None) for n in (5, 2, 9)
    ]
    added = store.add_words(drafts, T0)

    assert ids(store.learn_queue()) == [entry.id for entry in added]


def test_the_order_survives_a_restart(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b, c = add(store, 1), add(store, 2), add(store, 3)
    store.reorder_learn_queue([c, a])

    reopened = build_store(tmp_path)
    assert ids(reopened.learn_queue()) == [c, a, b]


def test_a_word_learned_in_every_direction_is_not_in_the_queue(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a = add(store, 1)
    add(store, 2, familiarity=Familiarity.WELL)

    assert ids(store.learn_queue()) == [a]


def test_a_word_learned_in_some_directions_stays_in_the_queue(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b = add(store, 1), add(store, 2)
    answer(store, a, Direction.HANGUL_TO_TRANSLATION)

    assert ids(store.learn_queue()) == [a, b]
    assert ids(store.learn_queue(directions={Direction.HANGUL_TO_TRANSLATION})) == [b]


def test_the_tag_filter_keeps_the_queue_order(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a = add(store, 1, tags=("food",))
    add(store, 2)
    c = add(store, 3, tags=("food",))
    store.reorder_learn_queue([c])

    assert ids(store.learn_queue(tag="food")) == [c, a]


def test_new_words_follow_the_queue(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b, c = add(store, 1), add(store, 2), add(store, 3)
    store.reorder_learn_queue([c])

    assert ids(store.new_words(limit=2)) == [c, a]
    assert ids(store.new_words(limit=5)) == [c, a, b]


@pytest.mark.parametrize(
    "requested",
    [
        pytest.param(["a", "unknown"], id="unknown-id"),
        pytest.param(["b", "a", "b"], id="repeated-id"),
        pytest.param(["learned"], id="learned-in-every-direction"),
    ],
)
def test_a_refused_reorder_changes_nothing(tmp_path: Path, requested: list[str]) -> None:
    store = build_store(tmp_path)
    a, b = add(store, 1), add(store, 2)
    by_name = {"a": a, "b": b, "learned": add(store, 3, familiarity=Familiarity.WELL)}
    by_name["unknown"] = max(by_name.values()) + 100

    with pytest.raises(QueueOrderError):
        store.reorder_learn_queue([by_name[name] for name in requested])

    assert issubclass(QueueOrderError, ValueError)
    assert ids(store.learn_queue()) == [a, b]


def test_deleting_a_word_takes_it_out_of_the_queue(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b = add(store, 1), add(store, 2)
    assert store.delete_word(a)

    assert ids(store.learn_queue()) == [b]
    store.reorder_learn_queue([b])
    assert ids(store.learn_queue()) == [b]


# ---------------------------------------------------------------------------------
# Review candidates and reading words by id
# ---------------------------------------------------------------------------------


def test_review_candidates_are_the_due_words_then_the_others_soonest_first(
    tmp_path: Path,
) -> None:
    store = build_store(tmp_path)
    later = add(store, 1)
    answer(store, later, Direction.HANGUL_TO_TRANSLATION, days=3)
    overdue = add(store, 2)
    answer(store, overdue, Direction.HANGUL_TO_TRANSLATION)
    add(store, 3)  # never learned: not a candidate

    assert ids(store.review_candidates()) == [overdue, later]


def test_review_candidates_only_count_the_ticked_directions(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    one_way = add(store, 1)
    answer(store, one_way, Direction.VOICE_TO_HANGUL)
    other_way = add(store, 2)
    answer(store, other_way, Direction.HANGUL_TO_TRANSLATION)

    assert ids(store.review_candidates(directions={Direction.VOICE_TO_HANGUL})) == [one_way]


def test_review_candidates_filter_by_tag(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    tagged = add(store, 1, familiarity=Familiarity.WELL, tags=("food",))
    add(store, 2, familiarity=Familiarity.WELL)

    assert ids(store.review_candidates(tag="food")) == [tagged]


def test_get_words_keeps_the_order_asked_and_skips_unknown_ids(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    a, b = add(store, 1), add(store, 2)

    assert ids(store.get_words([b, 999, a])) == [b, a]
    assert not store.get_words([])
