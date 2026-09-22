"""Tests for SQLite persistence: vocab-core T04's `storage` package.

Framing-mode note: none of the production code below exists yet. These tests are written
from vocab-core T04's acceptance criteria and test contract, and they define the contract
the implementation must satisfy. Two modules, `oral_korean.storage.database` and
`oral_korean.storage.words`:

- `database.MIGRATIONS: Final[tuple[str, ...]]` - one SQL script per migration, applied
  in order.
- `database.SchemaVersionError(RuntimeError)` - the file's `user_version` is ahead of the
  code's; the message names both versions.
- `database.Database(path: Path, *, migrations: Sequence[str] = MIGRATIONS)` - building it
  does no I/O; `path` is a read-only attribute; `transaction()` is a context manager
  yielding a `sqlite3.Connection` (the first one creates the parent directory, the file and
  the schema; commit on success, rollback and re-raise on any exception, connection closed
  always).
- `words.DuplicateWordError(ValueError)` - `korean: str`, the colliding Korean, named in
  the message.
- `words.TagCount` (frozen): `tag: str`, `count: int`.
- `words.WordStore(database: Database)`:
  - `add_words(entries, at) -> tuple[VocabularyWord, ...]`, `entries` a sequence of
    `(WordDraft, (MemoryState, ReviewRecord) | None)` pairs, atomic.
  - `get_word(word_id) -> VocabularyWord | None`
  - `list_words(*, tag=None) -> tuple[VocabularyWord, ...]`, in adding order, tag matched
    exactly.
  - `update_word(word_id, korean, translations, tags) -> VocabularyWord | None`, `None`
    for an unknown id; familiarity, memory, history and the adding instant are never
    touched.
  - `delete_word(word_id) -> bool`
  - `tag_counts() -> tuple[TagCount, ...]`, sorted by tag.
  - `history(word_id) -> tuple[ReviewRecord, ...]`, chronological, `()` for an unknown id.

Decisions taken here that the ticket leaves open, flagged in the hand-back report:

1. **`DuplicateWordError(korean: str)`**: one positional parameter, pinned by a signature
   test, since the ticket names the attribute but not the constructor.
2. **A failing migration's error is read as `sqlite3.Error`** (or a subclass): the ticket
   names no dedicated exception for this case, unlike `SchemaVersionError` and
   `DuplicateWordError`, which are pinned by name.
3. **`Database.path` is read-only**: setting it is expected to raise `AttributeError`. The
   ticket says "exposed as a read-only attribute" without naming the mechanism.
4. **Updating a word without changing its Korean is not a self-collision.** The ticket
   pins that updating *onto another word's* match key is refused; a no-op on one's own key
   is exercised here because it is the natural trap in that rule's implementation.
5. **`history` is proven chronological with at most one record.** This ticket's own API
   can only ever produce the seed record through `add_words`; recording an answered
   review arrives with `vocab-sessions` T03. The ordering claim is exercised on that one
   record (and on the empty case), not on a multi-record history.

Real SQLite files under `tmp_path` throughout, never a mock of `sqlite3`. Memory states and
seed records come from `srs.memory.seed(..., fuzzing=False)` at the fixed instant `T0`,
never built by hand. Direct `sqlite3.connect()` access is used in exactly two places, both
explicitly sanctioned by the ticket: reading `word_tags` and `reviews` row counts after a
cascade, and preparing a file with a future `user_version` before the refusal test. Every
other check goes through `Database`/`WordStore`, including through the `sqlite3.Connection`
a `transaction()` call yields.
"""

from __future__ import annotations

import dataclasses
import inspect
import os
import sqlite3
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import signature_shape

import oral_korean.config
from oral_korean.config import AppConfig
from oral_korean.exercises.vocab_words import VocabularyWord, make_draft
from oral_korean.srs.memory import (
    Familiarity,
    Grade,
    MemoryState,
    ReviewRecord,
    apply_grade,
    seed,
)
from oral_korean.storage.database import MIGRATIONS, Database, SchemaVersionError
from oral_korean.storage.words import DuplicateWordError, TagCount, WordStore

T0 = datetime(2026, 9, 22, 9, 0, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[1]


def word(n: int) -> str:
    """A distinct one-syllable Hangul word, so fixtures never collide by match key."""
    return chr(0xAC00 + n)


def build_store(base_dir: Path) -> WordStore:
    """A fresh `WordStore` over a fresh `Database` file under `base_dir`."""
    return WordStore(Database(base_dir / "oral-korean.sqlite3"))


def seed_pair(familiarity: Familiarity, at: datetime = T0) -> tuple[MemoryState, ReviewRecord]:
    """`seed(familiarity, at, fuzzing=False)`, asserted non-`None` for a level that seeds."""
    result = seed(familiarity, at, fuzzing=False)
    assert result is not None, f"{familiarity} must seed a memory state"
    return result


class _Boom(Exception):
    """A marker exception, so a rollback test proves the real error is re-raised, not eaten."""


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


def test_migrations_is_a_non_empty_tuple_of_sql_scripts() -> None:
    """At least migration 1 (the words schema) exists, each script a non-blank string."""
    assert isinstance(MIGRATIONS, tuple)
    assert len(MIGRATIONS) >= 1
    assert all(isinstance(script, str) and script.strip() for script in MIGRATIONS)


def test_schema_version_error_is_a_runtime_error() -> None:
    """A file the code cannot read is a runtime condition, not a caller mistake."""
    assert issubclass(SchemaVersionError, RuntimeError)


def test_duplicate_word_error_is_a_value_error_naming_the_colliding_korean() -> None:
    """One error type for every refusal, as `WordEntryError` is for `vocab_words`."""
    error = DuplicateWordError("사과")

    assert isinstance(error, ValueError)
    assert error.korean == "사과"
    assert "사과" in str(error)


def test_tag_count_is_a_frozen_value_with_tag_and_count() -> None:
    """T05 serialises this directly; a mutable count could drift from the database."""
    tag_count = TagCount(tag="food", count=2)
    names = [field.name for field in dataclasses.fields(tag_count)]

    assert names == ["tag", "count"]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(tag_count, name, None)


def test_database_defaults_its_migrations_to_the_modules_own_tuple() -> None:
    """The keyword default really is `MIGRATIONS`, not an empty tuple that happens to work."""
    default = inspect.signature(Database).parameters["migrations"].default

    assert default == MIGRATIONS


def test_database_path_is_read_only(tmp_path: Path) -> None:
    """A test, or a caller, must not be able to repoint an open database mid-use."""
    db = Database(tmp_path / "oral-korean.sqlite3")

    with pytest.raises(AttributeError):
        setattr(db, "path", tmp_path / "elsewhere.sqlite3")  # noqa: B010 - read-only property


def test_the_project_root_is_computed_exactly_once_in_config() -> None:
    """A11 (numbers-exercise T02 audit): the database path is the third default built from
    the root; a second raw expression would repeat the mistake the extraction fixed.
    """
    source = inspect.getsource(oral_korean.config)

    assert source.count("Path(__file__).resolve()") == 1


@pytest.mark.parametrize(
    ("target", "positional", "keyword_only"),
    [
        pytest.param(Database, ["path"], ["migrations"], id="Database"),
        pytest.param(Database.transaction, ["self"], [], id="Database.transaction"),
        pytest.param(DuplicateWordError, ["korean"], [], id="DuplicateWordError"),
        pytest.param(WordStore, ["database"], [], id="WordStore"),
        pytest.param(
            WordStore.add_words, ["self", "entries", "at"], [], id="WordStore.add_words"
        ),
        pytest.param(WordStore.get_word, ["self", "word_id"], [], id="WordStore.get_word"),
        pytest.param(WordStore.list_words, ["self"], ["tag"], id="WordStore.list_words"),
        pytest.param(
            WordStore.update_word,
            ["self", "word_id", "korean", "translations", "tags"],
            [],
            id="WordStore.update_word",
        ),
        pytest.param(
            WordStore.delete_word, ["self", "word_id"], [], id="WordStore.delete_word"
        ),
        pytest.param(WordStore.tag_counts, ["self"], [], id="WordStore.tag_counts"),
        pytest.param(WordStore.history, ["self", "word_id"], [], id="WordStore.history"),
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    target: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """Names and order are part of the contract T05 calls by position."""
    assert signature_shape(target) == (positional, keyword_only)


# ---------------------------------------------------------------------------------
# Database and migrations
# ---------------------------------------------------------------------------------


def test_constructing_the_database_object_does_no_io(tmp_path: Path) -> None:
    """Lazy: not even the parent directory exists until the first unit of work."""
    path = tmp_path / "missing" / "oral-korean.sqlite3"

    db = Database(path)

    assert db.path == path
    assert not path.parent.exists()
    assert not path.exists()


def test_the_first_unit_of_work_creates_the_directory_the_file_and_the_schema(
    tmp_path: Path,
) -> None:
    """Entering `transaction()` is what does the work, even with an empty body."""
    path = tmp_path / "missing" / "oral-korean.sqlite3"
    db = Database(path)

    with db.transaction() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert path.parent.is_dir()
    assert path.is_file()
    assert version == len(MIGRATIONS)


def test_reopening_an_up_to_date_file_applies_nothing_and_loses_nothing(
    tmp_path: Path,
) -> None:
    """A fresh `Database` object on the same path sees what the first one wrote."""
    path = tmp_path / "oral-korean.sqlite3"
    first_store = WordStore(Database(path))
    draft = make_draft(word(0), "a", [], Familiarity.NEW)
    (added,) = first_store.add_words([(draft, None)], T0)

    second_db = Database(path)
    with second_db.transaction() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    second_store = WordStore(second_db)

    assert version == len(MIGRATIONS)
    assert second_store.get_word(added.id) == added


def test_a_file_newer_than_the_code_is_refused_with_both_versions_named(
    tmp_path: Path,
) -> None:
    """The file's bytes must be untouched: a raw connection sets the version up front,
    per the ticket's own recipe, so the comparison is not against a file `Database` wrote.
    """
    path = tmp_path / "oral-korean.sqlite3"
    future_version = len(MIGRATIONS) + 1
    with sqlite3.connect(path) as raw:
        raw.execute(f"PRAGMA user_version = {future_version}")
        raw.commit()
    before = path.read_bytes()
    db = Database(path)

    with pytest.raises(SchemaVersionError) as excinfo, db.transaction():
        pass

    message = str(excinfo.value)
    assert str(future_version) in message
    assert str(len(MIGRATIONS)) in message
    assert path.read_bytes() == before


def test_a_migration_that_fails_halfway_leaves_the_version_and_schema_untouched(
    tmp_path: Path,
) -> None:
    """`executescript()` commits any open transaction first, so a naive implementation
    would leave the failed migration's table behind; a real one rolls the whole script back.
    """
    path = tmp_path / "oral-korean.sqlite3"
    good = "CREATE TABLE scratch_a (id INTEGER PRIMARY KEY);"
    fails_halfway = "CREATE TABLE scratch_b (id INTEGER PRIMARY KEY);\nNOT VALID SQL;"
    db = Database(path, migrations=(good, fails_halfway))

    with pytest.raises(sqlite3.Error), db.transaction():
        pass

    reopened = Database(path, migrations=(good,))
    with reopened.transaction() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert version == 1
    assert "scratch_a" in table_names
    assert "scratch_b" not in table_names


def test_a_unit_of_work_that_raises_after_writing_leaves_nothing_visible(
    tmp_path: Path,
) -> None:
    """A scratch table, so the test does not depend on the words schema at all."""
    db = Database(tmp_path / "oral-korean.sqlite3")
    with db.transaction() as conn:
        conn.execute("CREATE TABLE scratch (id INTEGER PRIMARY KEY)")

    with pytest.raises(_Boom), db.transaction() as conn:
        conn.execute("INSERT INTO scratch (id) VALUES (1)")
        raise _Boom("simulated failure after a write")

    with db.transaction() as conn:
        count = conn.execute("SELECT COUNT(*) FROM scratch").fetchone()[0]
    assert count == 0


def test_deleting_a_word_cascades_to_its_tag_rows_and_history_rows(tmp_path: Path) -> None:
    """Foreign keys are on: the raw row counts are the ticket's own sanctioned direct access."""
    path = tmp_path / "oral-korean.sqlite3"
    store = WordStore(Database(path))
    draft = make_draft(word(1), "a", ["food", "fruit"], Familiarity.WELL)
    (added,) = store.add_words([(draft, seed_pair(Familiarity.WELL))], T0)

    assert store.delete_word(added.id) is True

    with sqlite3.connect(path) as raw:
        tag_rows = raw.execute(
            "SELECT COUNT(*) FROM word_tags WHERE word_id = ?", (added.id,)
        ).fetchone()[0]
        review_rows = raw.execute(
            "SELECT COUNT(*) FROM reviews WHERE word_id = ?", (added.id,)
        ).fetchone()[0]
    assert (tag_rows, review_rows) == (0, 0)


# ---------------------------------------------------------------------------------
# Words: adding
# ---------------------------------------------------------------------------------


def test_adding_a_new_word_returns_it_with_an_id_and_no_memory(tmp_path: Path) -> None:
    """Familiarity `new`: an id, the display form, ordered translations, sorted tags,
    the adding instant, and no memory state; reading it back by id gives the same value.
    """
    store = build_store(tmp_path)
    draft = make_draft(word(2), "apple; pomme", ["food", "fruit"], Familiarity.NEW)

    (added,) = store.add_words([(draft, None)], T0)

    assert isinstance(added, VocabularyWord)
    assert added.id is not None
    assert added.korean == word(2)
    assert added.translations == ("apple", "pomme")
    assert added.tags == ("food", "fruit")
    assert added.familiarity is Familiarity.NEW
    assert added.added_at == T0
    assert added.memory is None
    assert store.get_word(added.id) == added


def test_adding_a_word_seeded_well_reads_back_the_seeded_memory_exactly(
    tmp_path: Path,
) -> None:
    """Floats exact, datetimes equal and aware; the history holds exactly one seed record."""
    store = build_store(tmp_path)
    state, record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(3), "a", [], Familiarity.WELL)

    (added,) = store.add_words([(draft, (state, record))], T0)

    assert added.memory == state
    history = store.history(added.id)
    assert history == (record,)
    assert history[0].is_seed is True


def test_a_stored_memory_state_can_be_graded_again_without_error(tmp_path: Path) -> None:
    """The stored datetimes must satisfy fsrs's own UTC check: reading nothing raises."""
    store = build_store(tmp_path)
    state, record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(4), "a", [], Familiarity.WELL)
    (added,) = store.add_words([(draft, (state, record))], T0)
    assert added.memory is not None

    after, _ = apply_grade(added.memory, Grade.GOOD, added.memory.next_review, fuzzing=False)

    assert after.stability > 0


@pytest.mark.parametrize(
    "microsecond", [0, 500_000], ids=["zero-microseconds", "half-a-second"]
)
def test_a_datetime_round_trips_exactly_at_its_microsecond(
    tmp_path: Path, microsecond: int
) -> None:
    """Both ends of the second: microseconds are always written, never truncated."""
    store = build_store(tmp_path)
    at = T0.replace(microsecond=microsecond)
    state, record = seed_pair(Familiarity.WELL, at)
    draft = make_draft(word(5 + microsecond // 500_000), "a", [], Familiarity.WELL)

    (added,) = store.add_words([(draft, (state, record))], at)

    assert added.added_at == at
    assert added.memory == state


def test_a_batch_of_three_returns_distinct_ids_and_lists_in_batch_order(
    tmp_path: Path,
) -> None:
    """Three new words, three distinct ids, `list_words()` echoing the same order back."""
    store = build_store(tmp_path)
    drafts = [make_draft(word(10 + n), f"w{n}", [], Familiarity.NEW) for n in range(3)]

    added = store.add_words([(draft, None) for draft in drafts], T0)

    assert isinstance(added, tuple)
    assert len(added) == 3
    assert len({item.id for item in added}) == 3
    assert [item.korean for item in added] == [draft.korean for draft in drafts]
    assert store.list_words() == added


def test_a_batch_whose_third_draft_duplicates_a_stored_word_stores_nothing(
    tmp_path: Path,
) -> None:
    """A stored `사과`, a new `사 과`: the error names the already-stored spelling."""
    store = build_store(tmp_path)
    store.add_words([(make_draft("사과", "apple", [], Familiarity.NEW), None)], T0)
    drafts = [
        make_draft(word(20), "a", [], Familiarity.NEW),
        make_draft(word(21), "b", [], Familiarity.NEW),
        make_draft("사 과", "c", [], Familiarity.NEW),
    ]

    with pytest.raises(DuplicateWordError) as excinfo:
        store.add_words([(draft, None) for draft in drafts], T0)

    assert excinfo.value.korean == "사과"
    assert len(store.list_words()) == 1


def test_a_batch_with_two_drafts_sharing_a_match_key_names_the_earlier_one(
    tmp_path: Path,
) -> None:
    """The in-batch collision names the earlier draft's Korean, and stores neither."""
    store = build_store(tmp_path)
    first = make_draft("사과", "apple", [], Familiarity.NEW)
    second = make_draft("사 과", "pomme", [], Familiarity.NEW)

    with pytest.raises(DuplicateWordError) as excinfo:
        store.add_words([(first, None), (second, None)], T0)

    assert excinfo.value.korean == "사과"
    assert not store.list_words()


def test_add_words_with_a_naive_instant_raises_and_stores_nothing(tmp_path: Path) -> None:
    """A naive `at` is a caller bug, refused before anything is written."""
    store = build_store(tmp_path)
    draft = make_draft(word(30), "a", [], Familiarity.NEW)
    naive = datetime(2026, 9, 22, 9, 0, 0)

    with pytest.raises(ValueError):
        store.add_words([(draft, None)], naive)

    assert not store.list_words()


def test_stored_datetimes_read_back_aware_with_the_utc_object(tmp_path: Path) -> None:
    """`tzinfo is timezone.utc`, the exact object fsrs requires, not merely an equal offset."""
    store = build_store(tmp_path)
    state, record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(31), "a", [], Familiarity.WELL)

    (added,) = store.add_words([(draft, (state, record))], T0)

    assert added.added_at.tzinfo is UTC
    assert added.memory is not None
    assert added.memory.next_review.tzinfo is UTC
    assert added.memory.last_review.tzinfo is UTC
    history_record = store.history(added.id)[0]
    assert history_record.reviewed_at.tzinfo is UTC
    assert history_record.next_review.tzinfo is UTC


# ---------------------------------------------------------------------------------
# Words: reading
# ---------------------------------------------------------------------------------


def test_get_word_of_an_unknown_id_returns_none(tmp_path: Path) -> None:
    """Reading a word nobody stored is `None`, not an error."""
    store = build_store(tmp_path)

    assert store.get_word(999) is None


def test_list_words_of_an_empty_store_is_empty(tmp_path: Path) -> None:
    """Nothing added, nothing listed."""
    store = build_store(tmp_path)

    assert not store.list_words()


def test_list_words_filters_by_exact_tag(tmp_path: Path) -> None:
    """No filter lists everything; a known tag narrows it; an unknown tag is empty."""
    store = build_store(tmp_path)
    apple = make_draft(word(40), "apple", ["food"], Familiarity.NEW)
    run = make_draft(word(41), "run", ["verb"], Familiarity.NEW)
    pear = make_draft(word(42), "pear", ["food", "fruit"], Familiarity.NEW)
    added = store.add_words([(apple, None), (run, None), (pear, None)], T0)

    assert store.list_words() == added
    assert store.list_words(tag="food") == (added[0], added[2])
    assert store.list_words(tag="verb") == (added[1],)
    assert not store.list_words(tag="nonexistent")


def test_list_words_tag_filter_is_matched_exactly_not_normalised(tmp_path: Path) -> None:
    """Storage does not casefold: the caller (T05) is the one that normalises the tag."""
    store = build_store(tmp_path)
    (added,) = store.add_words(
        [(make_draft(word(43), "a", ["food"], Familiarity.NEW), None)], T0
    )

    assert not store.list_words(tag="Food")
    assert store.list_words(tag="food") == (added,)


# ---------------------------------------------------------------------------------
# Words: updating
# ---------------------------------------------------------------------------------


def test_update_word_changes_the_editable_fields_and_leaves_the_rest_untouched(
    tmp_path: Path,
) -> None:
    """Korean, translations and tags change; familiarity, memory, history and the adding
    instant are compared whole, before and after.
    """
    store = build_store(tmp_path)
    state, record = seed_pair(Familiarity.WELL)
    draft = make_draft(word(50), "apple", ["food"], Familiarity.WELL)
    (added,) = store.add_words([(draft, (state, record))], T0)
    history_before = store.history(added.id)

    updated = store.update_word(added.id, "능금", ("apple", "eating apple"), ("fruit",))

    assert updated is not None
    assert updated.id == added.id
    assert updated.korean == "능금"
    assert updated.translations == ("apple", "eating apple")
    assert updated.tags == ("fruit",)
    assert updated.familiarity == added.familiarity
    assert updated.added_at == added.added_at
    assert updated.memory == added.memory
    assert store.history(added.id) == history_before
    assert store.get_word(added.id) == updated


def test_updating_a_word_without_changing_its_korean_does_not_self_collide(
    tmp_path: Path,
) -> None:
    """The duplicate check must compare against other words, not the word being updated."""
    store = build_store(tmp_path)
    draft = make_draft(word(51), "apple", [], Familiarity.NEW)
    (added,) = store.add_words([(draft, None)], T0)

    updated = store.update_word(added.id, added.korean, ("apple", "pomme"), ())

    assert updated is not None
    assert updated.korean == added.korean
    assert updated.translations == ("apple", "pomme")


def test_update_onto_another_words_match_key_is_refused_and_changes_nothing(
    tmp_path: Path,
) -> None:
    """The same error as adding a duplicate, and both words read back unchanged."""
    store = build_store(tmp_path)
    first = make_draft("사과", "apple", [], Familiarity.NEW)
    second = make_draft(word(52), "pear", [], Familiarity.NEW)
    added_first, added_second = store.add_words([(first, None), (second, None)], T0)

    with pytest.raises(DuplicateWordError) as excinfo:
        store.update_word(added_second.id, "사 과", ("pear",), ())

    assert excinfo.value.korean == "사과"
    assert store.get_word(added_first.id) == added_first
    assert store.get_word(added_second.id) == added_second


def test_update_of_an_unknown_id_returns_none_without_creating_a_row(
    tmp_path: Path,
) -> None:
    """"Not found" is a `None`, never an exception and never a new row."""
    store = build_store(tmp_path)

    result = store.update_word(999, "사과", ("apple",), ())

    assert result is None
    assert not store.list_words()


# ---------------------------------------------------------------------------------
# Words: deleting
# ---------------------------------------------------------------------------------


def test_delete_of_an_unknown_id_returns_false_without_creating_a_row(
    tmp_path: Path,
) -> None:
    """"Not found" is `False`, never an exception and never a new row."""
    store = build_store(tmp_path)

    assert store.delete_word(999) is False
    assert not store.list_words()


def test_deleting_a_word_leaves_the_other_words_untouched(tmp_path: Path) -> None:
    """The word, its tags and its history are gone; a sibling word is exactly as it was."""
    store = build_store(tmp_path)
    keep = make_draft(word(60), "keep", [], Familiarity.NEW)
    gone = make_draft(word(61), "gone", [], Familiarity.NEW)
    kept, deleted = store.add_words([(keep, None), (gone, None)], T0)

    assert store.delete_word(deleted.id) is True

    assert store.get_word(deleted.id) is None
    assert store.get_word(kept.id) == kept
    assert store.list_words() == (kept,)


def test_ids_are_never_reused_after_a_delete(tmp_path: Path) -> None:
    """A stale id held by a browser tab must never come to point at a different word."""
    store = build_store(tmp_path)
    (first,) = store.add_words([(make_draft(word(62), "a", [], Familiarity.NEW), None)], T0)
    assert store.delete_word(first.id) is True

    (second,) = store.add_words([(make_draft(word(63), "b", [], Familiarity.NEW), None)], T0)

    assert second.id != first.id
    assert second.id > first.id


# ---------------------------------------------------------------------------------
# Words: tags and history
# ---------------------------------------------------------------------------------


def test_tag_counts_are_sorted_by_tag_and_update_after_a_delete(tmp_path: Path) -> None:
    """`food` on two words and `verb` on one; deleting the only `verb` word drops it."""
    store = build_store(tmp_path)
    apple = make_draft(word(70), "apple", ["food"], Familiarity.NEW)
    pear = make_draft(word(71), "pear", ["food"], Familiarity.NEW)
    run = make_draft(word(72), "run", ["verb"], Familiarity.NEW)
    added = store.add_words([(apple, None), (pear, None), (run, None)], T0)

    assert store.tag_counts() == (
        TagCount(tag="food", count=2),
        TagCount(tag="verb", count=1),
    )

    store.delete_word(added[2].id)

    assert store.tag_counts() == (TagCount(tag="food", count=2),)


def test_history_of_an_unknown_word_is_empty(tmp_path: Path) -> None:
    """No word, no history: `()`, not an error."""
    store = build_store(tmp_path)

    assert not store.history(999)


def test_history_of_an_unseeded_new_word_is_empty(tmp_path: Path) -> None:
    """`new` seeds nothing, so a word added new has no history entry either."""
    store = build_store(tmp_path)
    (added,) = store.add_words([(make_draft(word(73), "a", [], Familiarity.NEW), None)], T0)

    assert not store.history(added.id)


def test_history_is_returned_in_chronological_order(tmp_path: Path) -> None:
    """This ticket's own API can only ever write one record (the seed) per word: the
    ordering claim is pinned on that record so a later ticket that appends answered
    reviews inherits a sorted read, not an implementation that happens to insert in order.
    """
    store = build_store(tmp_path)
    state, record = seed_pair(Familiarity.VERY_WELL)
    draft = make_draft(word(74), "a", [], Familiarity.VERY_WELL)
    (added,) = store.add_words([(draft, (state, record))], T0)

    history = store.history(added.id)

    assert history == (record,)
    assert list(history) == sorted(history, key=lambda entry: entry.reviewed_at)


def test_unicode_round_trips_exactly_through_storage(tmp_path: Path) -> None:
    """NFC Hangul (composed by `make_draft` from an NFD input before storage ever sees it),
    an accented Latin word and an emoji: none of them may be mangled.
    """
    store = build_store(tmp_path)
    nfc_korean = unicodedata.normalize("NFC", "카페")
    draft = make_draft(
        unicodedata.normalize("NFD", nfc_korean), "café ; 🍎", ["café"], Familiarity.NEW
    )
    assert draft.korean == nfc_korean  # sanity: make_draft already composed it

    (added,) = store.add_words([(draft, None)], T0)
    fetched = store.get_word(added.id)

    assert fetched == added
    assert fetched is not None
    assert fetched.korean == nfc_korean
    assert fetched.translations == ("café", "🍎")
    assert fetched.tags == ("café",)


# ---------------------------------------------------------------------------------
# Configuration and isolation
# ---------------------------------------------------------------------------------


def test_constructing_app_config_creates_no_file_or_directory(tmp_path: Path) -> None:
    """Merely building the configuration must never touch the filesystem."""
    custom = tmp_path / "not-created" / "oral-korean.sqlite3"

    AppConfig(database_path=custom)

    assert not custom.exists()
    assert not custom.parent.exists()


def test_app_config_database_path_keyword_override_wins(tmp_path: Path) -> None:
    """A keyword argument beats both the environment and the default."""
    custom = tmp_path / "custom.sqlite3"

    config = AppConfig(database_path=custom)

    assert config.database_path == custom


def test_app_config_database_path_follows_the_environment_variable(tmp_path: Path) -> None:
    """With no keyword override, the default reads `ORAL_KOREAN_DATABASE_PATH`."""
    custom = tmp_path / "from-env" / "oral-korean.sqlite3"

    with patch.dict(os.environ, {"ORAL_KOREAN_DATABASE_PATH": str(custom)}):
        config = AppConfig()

    assert config.database_path == custom


def test_app_config_database_path_defaults_under_the_repository_data_directory_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the variable absent entirely, the default lives under the repository's `.data/`.

    `monkeypatch.delenv` rather than the autouse fixture's own value: this test needs to see
    what the default would be with nothing set, without ever creating a file.
    """
    monkeypatch.delenv("ORAL_KOREAN_DATABASE_PATH", raising=False)

    config = AppConfig()

    # Shape only: the real file may well exist once the app has been used, and this test
    # must neither depend on that nor touch it.
    assert config.database_path == REPO_ROOT / ".data" / "oral-korean.sqlite3"


def test_the_default_database_path_resolves_inside_a_temporary_directory_during_the_suite() -> (
    None
):
    """Proves the autouse fixture is in force: no test can ever reach the real `.data/`."""
    config = AppConfig()

    assert REPO_ROOT not in config.database_path.parents
