"""Tests for the vocabulary session: which directions a word is asked in, in what order, and
what is scored.

First written from vocab-sessions T02, rewritten from vocab-directions T02 before its
implementation: a session now asks each word in every direction it needs, spread among the
other words' questions, and the batch is shuffled with an injected random source. The rest of
the exercise (modes, grading, building and judging) is pinned in
`tests/test_exercises_vocab.py`. The direction choice is pinned here rather than there, as the
ticket's test contract puts it, because that file sits close to pylint's 1000-line module limit
and the choice only exists to feed the plan. Everything is imported from
`oral_korean.exercises.vocab`, which re-exports `vocab_session.py`.

- `SessionKind` (`StrEnum`): `LEARN` ("learn"), `REVIEW` ("review").
- `ItemKind` (`StrEnum`): `PRESENTATION` ("presentation"), `QUESTION` ("question").
- `directions_to_ask(word, kind, ticked, at) -> tuple[Direction, ...]`, in `Direction` order:
  learn, every ticked direction with no memory; review, every ticked learned direction due at
  `at` (`at >= next_review`), or, if none is due, every ticked learned direction (an early
  review). `()` leaves the word out of the session.
- `SessionItem` (frozen): `number` (1-based, unique, the handle an answer is recorded against),
  `kind`, `word`, `direction` (`None` for a presentation), `scored`.
- `DirectionResult(direction, correct)` and `WordResult(word_id, correct, directions)`, frozen;
  `directions` in `Direction` order, `correct` true only when every direction was right.
- `SessionSummary` (frozen): `results` (in batch order), `word_count`, `correct_count`,
  `question_count`, `correct_question_count`.
- `SessionProgress` (frozen): `words_done`, `word_count`, `questions_done`, `question_count`.
- `SessionPlan(kind, batch, *, rng=None)`, `batch` a sequence of `(word, directions)`, with
  `next_item()`, `record_answer(number, *, correct)`, `summary()` and `progress()`.
- `SessionStateError(ValueError)`: a recording the plan refuses.

The ordering rule the tests hold the plan to: at each step, among the words with scored
questions left other than the previous scored question's word, the one with the most left
(ties by the shuffled word order); the rule is waived once a single word has any left. A learn
session presents a word immediately before its first question. A miss, scored or practice,
appends an unscored practice question for the same (word, direction), up to two per pair.

Pure calls throughout: no file, no patching, no HTTP. Random sources are seeded
`random.Random`s and memory states come from `srs/` with fuzzing off.
"""

from __future__ import annotations

import dataclasses
import random
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from conftest import signature_shape

from oral_korean.exercises import vocab, vocab_session
from oral_korean.exercises.vocab import (
    Direction,
    DirectionResult,
    ItemKind,
    SessionItem,
    SessionKind,
    SessionPlan,
    SessionProgress,
    SessionStateError,
    SessionSummary,
    WordResult,
    directions_to_ask,
)
from oral_korean.exercises.vocab_words import VocabularyWord, same_memory
from oral_korean.srs.memory import Familiarity, MemoryState, seed

T0 = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
KINDS = list(SessionKind)
KIND_IDS = [kind.value for kind in KINDS]

H2T = Direction.HANGUL_TO_TRANSLATION
T2H = Direction.TRANSLATION_TO_HANGUL
V2H = Direction.VOICE_TO_HANGUL
V2T = Direction.VOICE_TO_TRANSLATION
ALL = tuple(Direction)

SEEDS = range(20)
"""Twenty seeded sources: enough that an order which never changes cannot hide."""

type Batch = list[tuple[VocabularyWord, Sequence[Direction]]]
type Answer = Callable[[SessionItem], bool]


def make_word(
    word_id: int, korean: str, memories: Mapping[Direction, MemoryState | None] | None = None
) -> VocabularyWord:
    """One stored word, with no memory in any direction unless `memories` says otherwise."""
    every = same_memory(None)
    every.update(memories or {})
    return VocabularyWord(word_id, korean, ("word",), (), Familiarity.NEW, T0, every)


JIP = make_word(1, "집")
SAGWA = make_word(3, "사과")
MUL = make_word(5, "물")


def numbered_words(count: int) -> list[VocabularyWord]:
    """`count` distinct words, so a long session never collides by id or by Korean."""
    return [make_word(100 + n, chr(0xAC00 + n)) for n in range(count)]


def every_direction(*words: VocabularyWord) -> Batch:
    return [(word, ALL) for word in words]


def make_plan(kind: SessionKind, batch: Batch, seed_value: int = 0) -> SessionPlan:
    return SessionPlan(kind, batch, rng=random.Random(seed_value))


def always_right(_item: SessionItem) -> bool:
    return True


def always_wrong(_item: SessionItem) -> bool:
    return False


def wrong_on(word: VocabularyWord, direction: Direction) -> Answer:
    """Every question for (`word`, `direction`) answered wrong, every other one right."""
    return lambda item: (item.word.id, item.direction) != (word.id, direction)


def scored_wrong_on(word: VocabularyWord, direction: Direction) -> Answer:
    """Only the scored question for (`word`, `direction`) answered wrong."""
    return lambda item: not (item.scored and (item.word.id, item.direction) == (word.id, direction))


def run_session(plan: SessionPlan, answer: Answer) -> list[SessionItem]:
    """Every item `plan` hands out, each question answered as `answer` decides.

    The cap is the termination proof: a plan that never ends fails here with a message instead
    of hanging the suite.
    """
    handed: list[SessionItem] = []
    while (item := plan.next_item()) is not None:
        handed.append(item)
        if item.kind is ItemKind.QUESTION:
            plan.record_answer(item.number, correct=answer(item))
        assert len(handed) <= 300, "the session handed out 300 items without ending"
    return handed


def scored(items: Sequence[SessionItem]) -> list[SessionItem]:
    return [item for item in items if item.scored]


def practice(items: Sequence[SessionItem]) -> list[SessionItem]:
    return [item for item in items if item.kind is ItemKind.QUESTION and not item.scored]


def pairs(items: Sequence[SessionItem]) -> list[tuple[int, Direction | None]]:
    return [(item.word.id, item.direction) for item in items]


def word_ids(items: Sequence[SessionItem]) -> list[int]:
    return [item.word.id for item in items]


def first_word_order(items: Sequence[SessionItem]) -> list[int]:
    """The word ids in the order each first appears."""
    return list(dict.fromkeys(word_ids(items)))


def assert_spread(questions: Sequence[SessionItem]) -> None:
    """Two consecutive questions share a word only once no other word has any left."""
    ids = word_ids(questions)
    for index in range(len(ids) - 1):
        if ids[index] == ids[index + 1]:
            assert set(ids[index + 1 :]) == {ids[index]}, ids


def signature(items: Sequence[SessionItem]) -> list[tuple[int, ItemKind, int, object, bool]]:
    return [(item.number, item.kind, item.word.id, item.direction, item.scored) for item in items]


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


def test_the_session_and_item_kinds_have_their_wire_values() -> None:
    """T03 serialises both: a learn or review session, a presentation or a question."""
    assert KIND_IDS == ["learn", "review"]
    assert [kind.value for kind in ItemKind] == ["presentation", "question"]
    assert SessionKind("review") is SessionKind.REVIEW


def test_a_refused_recording_is_a_value_error() -> None:
    assert issubclass(SessionStateError, ValueError)


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        pytest.param(SessionPlan, ["kind", "batch"], ["rng"], id="SessionPlan"),
        pytest.param(SessionPlan.next_item, ["self"], [], id="next_item"),
        pytest.param(SessionPlan.record_answer, ["self", "number"], ["correct"], id="record"),
        pytest.param(SessionPlan.summary, ["self"], [], id="summary"),
        pytest.param(SessionPlan.progress, ["self"], [], id="progress"),
        pytest.param(
            directions_to_ask, ["word", "kind", "ticked", "at"], [], id="directions_to_ask"
        ),
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """`correct` is keyword-only: a stray positional `False` would record the wrong outcome. The
    random source is keyword-only too, so it cannot be passed where the batch goes."""
    assert signature_shape(function) == (positional, keyword_only)


def test_the_session_values_are_frozen_with_the_agreed_fields() -> None:
    """An item is the handle an answer is recorded against; the summary and the progress are
    what the routes serialise."""
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T])])
    item = plan.next_item()
    assert item is not None
    plan.record_answer(item.number, correct=True)
    summary = plan.summary()
    result = summary.results[0]
    progress = plan.progress()

    assert isinstance(summary, SessionSummary)
    assert isinstance(progress, SessionProgress)
    assert {field.name for field in dataclasses.fields(item)} == {
        "number",
        "kind",
        "word",
        "direction",
        "scored",
    }
    assert {field.name for field in dataclasses.fields(summary)} == {
        "results",
        "word_count",
        "correct_count",
        "question_count",
        "correct_question_count",
    }
    assert [field.name for field in dataclasses.fields(result)] == [
        "word_id",
        "correct",
        "directions",
    ]
    assert [field.name for field in dataclasses.fields(result.directions[0])] == [
        "direction",
        "correct",
    ]
    assert {field.name for field in dataclasses.fields(progress)} == {
        "words_done",
        "word_count",
        "questions_done",
        "question_count",
    }
    for value in (item, summary, result, result.directions[0], progress):
        for field in dataclasses.fields(value):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(value, field.name, None)


@pytest.mark.parametrize(
    "name",
    [
        "SessionPlan",
        "SessionItem",
        "SessionSummary",
        "WordResult",
        "DirectionResult",
        "SessionProgress",
    ],
)
def test_the_session_names_are_re_exported_by_the_exercise_module(name: str) -> None:
    """One import covers the exercise: `vocab` hands out the very objects `vocab_session`
    defines, not copies."""
    assert getattr(vocab, name) is getattr(vocab_session, name)
    assert name in vocab.__all__


def test_draw_direction_is_gone() -> None:
    """The direction now comes from the plan: a leftover random draw is a second way to pick
    one, and a route that reached for it would ask a direction nobody chose."""
    assert not hasattr(vocab, "draw_direction")
    assert "draw_direction" not in vocab.__all__
    assert "directions_to_ask" in vocab.__all__


# ---------------------------------------------------------------------------------
# Which directions a word is asked in
# ---------------------------------------------------------------------------------


def learned_on(at: datetime) -> MemoryState:
    """The `well` seed laid on `at`: next review two days later, a delay FSRS never fuzzes."""
    seeded = seed(Familiarity.WELL, at, fuzzing=False)
    assert seeded is not None
    return seeded[0]


DUE = learned_on(T0)
AT = DUE.next_review
"""The fixed instant: exactly when `DUE` falls due, so `DUE` is due and nothing later is."""
NOT_DUE = learned_on(AT)
assert NOT_DUE.next_review > AT  # sanity: the second seed is two days ahead of the instant


@pytest.mark.parametrize(
    ("kind", "memories", "ticked", "at", "expected"),
    [
        pytest.param(SessionKind.LEARN, {}, set(ALL), AT, ALL, id="learn-new-word-all-ticked"),
        pytest.param(
            SessionKind.LEARN,
            {V2H: DUE},
            list(ALL),
            AT,
            (H2T, T2H, V2T),
            id="learn-learned-only-voice-to-hangul",
        ),
        pytest.param(
            SessionKind.LEARN,
            {H2T: DUE, T2H: NOT_DUE},
            {H2T, T2H},
            AT,
            (),
            id="learn-learned-in-every-ticked-direction",
        ),
        pytest.param(
            SessionKind.LEARN,
            {},
            [V2T, H2T],
            AT,
            (H2T, V2T),
            id="learn-only-the-ticked-ones-in-declaration-order",
        ),
        pytest.param(
            SessionKind.LEARN,
            {H2T: DUE},
            frozenset(ALL),
            AT,
            (T2H, V2H, V2T),
            id="learn-never-asks-a-learned-direction-even-due",
        ),
        pytest.param(
            SessionKind.REVIEW,
            {H2T: DUE, V2T: DUE, T2H: NOT_DUE, V2H: NOT_DUE},
            set(ALL),
            AT,
            (H2T, V2T),
            id="review-two-due-all-ticked",
        ),
        pytest.param(
            SessionKind.REVIEW,
            {V2H: DUE, H2T: NOT_DUE, T2H: NOT_DUE},
            {H2T, T2H, V2T},
            AT,
            (H2T, T2H),
            id="review-due-only-unticked-so-every-ticked-learned-one",
        ),
        pytest.param(
            SessionKind.REVIEW,
            {H2T: DUE},
            {T2H, V2H, V2T},
            AT,
            (),
            id="review-no-learned-ticked-direction",
        ),
        pytest.param(SessionKind.REVIEW, {}, set(ALL), AT, (), id="review-new-word"),
        pytest.param(
            SessionKind.REVIEW,
            {H2T: DUE, T2H: NOT_DUE},
            set(ALL),
            AT,
            (H2T,),
            id="review-due-exactly-at-its-next-review",
        ),
        pytest.param(
            SessionKind.REVIEW,
            {H2T: DUE, T2H: NOT_DUE},
            set(ALL),
            AT - timedelta(seconds=1),
            (H2T, T2H),
            id="review-a-second-early-is-an-early-review",
        ),
        pytest.param(
            SessionKind.REVIEW,
            {H2T: DUE},
            set(ALL),
            AT,
            (H2T,),
            id="review-never-asks-an-unlearned-direction",
        ),
        pytest.param(
            SessionKind.REVIEW,
            {T2H: NOT_DUE},
            set(ALL),
            AT,
            (T2H,),
            id="review-early-never-asks-an-unlearned-direction",
        ),
    ],
)
def test_the_directions_a_word_is_asked_in(
    kind: SessionKind,
    memories: Mapping[Direction, MemoryState | None],
    ticked: Collection[Direction],
    at: datetime,
    expected: tuple[Direction, ...],
) -> None:
    """A learn session asks what has never been asked; a review asks what is due, or every
    learned direction when the user reviews a word early. Only ticked directions, always in
    `Direction` order, and `()` for a word the session leaves out."""
    word = make_word(1, "집", memories)

    assert directions_to_ask(word, kind, ticked, at) == expected


# ---------------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("seed_value", SEEDS)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_three_words_in_four_directions_are_each_asked_once_and_never_back_to_back(
    kind: SessionKind, seed_value: int
) -> None:
    """Twelve scored questions, each (word, direction) exactly once, and never the same word
    twice in a row: with three words holding four each, the spread is always possible."""
    plan = make_plan(kind, every_direction(JIP, SAGWA, MUL), seed_value)

    items = run_session(plan, always_right)
    questions = scored(items)
    ids = word_ids(questions)

    assert len(questions) == 12
    assert Counter(pairs(questions)) == {
        (word.id, direction): 1 for word in (JIP, SAGWA, MUL) for direction in ALL
    }
    assert all(earlier != later for earlier, later in zip(ids, ids[1:], strict=False)), ids
    assert practice(items) == []


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_single_word_is_asked_in_its_directions_back_to_back(kind: SessionKind) -> None:
    """With one word left the rule is waived: nothing else could go in between."""
    plan = make_plan(kind, [(JIP, [H2T, V2H, V2T])])

    items = run_session(plan, always_right)
    questions = [item for item in items if item.kind is ItemKind.QUESTION]

    assert len(questions) == 3
    assert all(item.scored and item.word.id == JIP.id for item in questions)
    assert sorted(item.direction for item in questions if item.direction) == sorted([H2T, V2H, V2T])


@pytest.mark.parametrize("seed_value", SEEDS)
def test_a_word_asks_twice_in_a_row_only_once_the_others_are_done(seed_value: int) -> None:
    """One word in four directions, two in one: 집 must take the gaps while they last, and only
    its last questions may follow each other."""
    batch: Batch = [(JIP, ALL), (SAGWA, [H2T]), (MUL, [V2T])]
    plan = make_plan(SessionKind.REVIEW, batch, seed_value)

    questions = scored(run_session(plan, always_right))

    assert len(questions) == 6
    assert_spread(questions)


@pytest.mark.parametrize("seed_value", SEEDS)
def test_a_batch_that_can_be_spread_all_the_way_is(seed_value: int) -> None:
    """Four, two and two: the word with the most left goes whenever it may, which leaves no
    two neighbours alike. A plan that only avoided repeats while it could would end 집, 집."""
    batch: Batch = [(JIP, ALL), (SAGWA, [H2T, T2H]), (MUL, [V2H, V2T])]
    plan = make_plan(SessionKind.REVIEW, batch, seed_value)

    ids = word_ids(scored(run_session(plan, always_right)))

    assert len(ids) == 8
    assert all(earlier != later for earlier, later in zip(ids, ids[1:], strict=False)), ids


@pytest.mark.parametrize("seed_value", SEEDS)
def test_the_word_with_the_most_questions_is_asked_first(seed_value: int) -> None:
    """Whatever the shuffle, the greedy order starts with the longest list."""
    batch: Batch = [(JIP, [H2T]), (SAGWA, ALL), (MUL, [H2T, T2H])]
    plan = make_plan(SessionKind.REVIEW, batch, seed_value)

    questions = scored(run_session(plan, always_right))

    assert questions[0].word.id == SAGWA.id


@pytest.mark.parametrize("seed_value", SEEDS)
def test_a_learn_session_presents_each_word_once_right_before_its_first_question(
    seed_value: int,
) -> None:
    """A new word is shown openly, then asked; never asked before it is shown, never shown
    twice. Nothing records a presentation, so it is done once handed out."""
    batch: Batch = [(JIP, ALL), (SAGWA, [H2T]), (MUL, [T2H, V2T])]
    plan = make_plan(SessionKind.LEARN, batch, seed_value)

    items = run_session(plan, always_right)

    presentations = [item for item in items if item.kind is ItemKind.PRESENTATION]
    assert sorted(word_ids(presentations)) == sorted([JIP.id, SAGWA.id, MUL.id])
    for presentation in presentations:
        assert (presentation.direction, presentation.scored) == (None, False)
        position = items.index(presentation)
        following = items[position + 1]
        assert (following.kind, following.word.id) == (ItemKind.QUESTION, presentation.word.id)
        assert presentation.word.id not in word_ids(items[:position])


@pytest.mark.parametrize("seed_value", SEEDS)
def test_a_review_session_presents_nothing(seed_value: int) -> None:
    plan = make_plan(SessionKind.REVIEW, every_direction(JIP, SAGWA), seed_value)

    items = run_session(plan, always_right)

    assert all(item.kind is ItemKind.QUESTION and item.direction is not None for item in items)


def test_the_random_source_shuffles_the_order_of_the_words() -> None:
    """The batch comes ordered (oldest new or most overdue first); the session asks it in a
    random order. Some seed has to move the first word, and every seed keeps the batch's
    words."""
    batch = every_direction(*numbered_words(4))
    batch_order = [word.id for word, _ in batch]

    orders = [
        first_word_order(run_session(make_plan(SessionKind.REVIEW, batch, value), always_right))
        for value in SEEDS
    ]

    assert all(sorted(order) == sorted(batch_order) for order in orders)
    assert any(order != batch_order for order in orders)


def test_the_random_source_shuffles_the_directions_of_a_word() -> None:
    """Directions come in `Direction` order; asking them always in that order would teach the
    order, not the word."""
    orders = {
        tuple(pairs(run_session(make_plan(SessionKind.REVIEW, [(JIP, ALL)], value), always_right)))
        for value in SEEDS
    }

    for order in orders:
        assert sorted(direction for _, direction in order if direction) == sorted(ALL)
    assert len(orders) > 1


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_the_same_seed_gives_the_same_session(kind: SessionKind) -> None:
    """Deterministic under an injected source, practice included: what makes every other
    ordering test here reproducible."""
    batch: Batch = [(JIP, ALL), (SAGWA, [H2T, V2T]), (MUL, [T2H])]
    answer = wrong_on(SAGWA, V2T)

    first = run_session(make_plan(kind, batch, 7), answer)
    second = run_session(make_plan(kind, batch, 7), answer)

    assert signature(first) == signature(second)


def test_item_numbers_are_unique_and_start_at_one() -> None:
    plan = make_plan(SessionKind.LEARN, every_direction(JIP, SAGWA), 3)

    numbers = [item.number for item in run_session(plan, always_wrong)]

    assert len(set(numbers)) == len(numbers)
    assert min(numbers) == 1


# ---------------------------------------------------------------------------------
# Practice repeats
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("seed_value", SEEDS)
def test_a_question_missed_every_time_comes_back_twice_and_no_more(seed_value: int) -> None:
    """Two unscored repeats of the missed (word, direction), then none; the summary reports
    the scored attempt."""
    batch: Batch = [(JIP, [H2T, T2H]), (SAGWA, [H2T])]
    plan = make_plan(SessionKind.REVIEW, batch, seed_value)

    items = run_session(plan, wrong_on(JIP, H2T))

    assert pairs(practice(items)) == [(JIP.id, H2T), (JIP.id, H2T)]
    jip = plan.summary().results[0]
    assert jip.word_id == JIP.id
    assert jip.directions == (
        DirectionResult(direction=H2T, correct=False),
        DirectionResult(direction=T2H, correct=True),
    )


def test_a_practice_question_answered_right_ends_the_repeats() -> None:
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T, T2H])])

    items = run_session(plan, scored_wrong_on(JIP, T2H))

    assert pairs(practice(items)) == [(JIP.id, T2H)]


def test_the_practice_cap_is_per_word_and_direction() -> None:
    """A word missed in two directions gets two repeats in each: the cap is not shared."""
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T, V2H]), (SAGWA, [T2H])])

    items = run_session(plan, lambda item: item.word.id != JIP.id)

    assert Counter(pairs(practice(items))) == {(JIP.id, H2T): 2, (JIP.id, V2H): 2}


@pytest.mark.parametrize("seed_value", SEEDS)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_practice_comes_after_every_scored_question(kind: SessionKind, seed_value: int) -> None:
    """A missed question is appended at the end of the queue, behind every scored one still
    waiting: the scored attempts are all taken before any practice."""
    batch: Batch = [(JIP, [H2T, T2H]), (SAGWA, [V2H, V2T]), (MUL, [H2T, V2T])]
    plan = make_plan(kind, batch, seed_value)

    items = run_session(plan, always_wrong)
    last_scored = max(index for index, item in enumerate(items) if item.scored)
    first_practice = min(items.index(item) for item in practice(items))

    assert last_scored < first_practice
    assert Counter(pairs(practice(items))) == {
        (word.id, direction): 2 for word, directions in batch for direction in directions
    }


@pytest.mark.parametrize("count", [1, 3, 10], ids=["one-word", "three-words", "ten-words"])
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_session_of_nothing_but_wrong_answers_still_ends(kind: SessionKind, count: int) -> None:
    """At most three questions per (word, direction), whatever the user does. Asked again once
    over, the plan still says it is finished."""
    plan = make_plan(kind, every_direction(*numbered_words(count)))

    items = run_session(plan, always_wrong)
    questions = [item for item in items if item.kind is ItemKind.QUESTION]

    assert len(questions) <= 3 * 4 * count
    assert plan.next_item() is None
    assert plan.next_item() is None


@pytest.mark.parametrize(
    "answer", [always_right, always_wrong], ids=["every-answer-right", "every-answer-wrong"]
)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_every_word_and_direction_gets_exactly_one_scored_question(
    kind: SessionKind, answer: Answer
) -> None:
    """FSRS sees each (word, direction)'s first attempt and nothing else: practice cannot score
    one twice, and no pair is forgotten."""
    batch: Batch = [(JIP, [V2T]), (SAGWA, ALL), (MUL, [T2H, H2T])]
    plan = make_plan(kind, batch, 11)

    items = run_session(plan, answer)

    assert Counter(pairs(scored(items))) == {
        (word.id, direction): 1 for word, directions in batch for direction in directions
    }
    assert all(item.kind is ItemKind.QUESTION for item in scored(items))


def test_asking_for_the_next_item_again_returns_the_same_unanswered_question() -> None:
    """No skipping a hard question by asking for the next one: it stands until answered."""
    plan = make_plan(SessionKind.REVIEW, every_direction(JIP, SAGWA))

    first = plan.next_item()
    assert first is not None
    assert plan.next_item() == first

    plan.record_answer(first.number, correct=True)
    second = plan.next_item()

    assert second is not None
    assert second.number != first.number
    assert second.word.id != first.word.id


# ---------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------


def test_recording_an_answer_twice_for_the_same_item_is_refused() -> None:
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T])])
    item = plan.next_item()
    assert item is not None
    plan.record_answer(item.number, correct=True)

    with pytest.raises(SessionStateError):
        plan.record_answer(item.number, correct=False)


@pytest.mark.parametrize(
    "number", [pytest.param(1, id="not-handed-out-yet"), pytest.param(99, id="no-such-item")]
)
def test_recording_an_answer_for_an_item_never_handed_out_is_refused(number: int) -> None:
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T])])

    with pytest.raises(SessionStateError):
        plan.record_answer(number, correct=True)


def test_recording_an_answer_for_a_presentation_is_refused() -> None:
    plan = make_plan(SessionKind.LEARN, [(JIP, [H2T])])
    item = plan.next_item()
    assert item is not None
    assert item.kind is ItemKind.PRESENTATION

    with pytest.raises(SessionStateError):
        plan.record_answer(item.number, correct=True)


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_session_over_no_words_at_all_is_refused(kind: SessionKind) -> None:
    """The route answers 409 when there is nothing to ask; an empty plan is a bug."""
    with pytest.raises(ValueError):
        make_plan(kind, [])


@pytest.mark.parametrize(
    "batch",
    [
        pytest.param([(JIP, [H2T]), (SAGWA, [H2T]), (JIP, [H2T])], id="same-directions"),
        pytest.param([(JIP, [H2T]), (JIP, [T2H])], id="other-directions"),
    ],
)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_batch_holding_the_same_word_twice_is_refused(kind: SessionKind, batch: Batch) -> None:
    """Twice in a batch, a word would be presented twice and its progress counted twice."""
    with pytest.raises(ValueError):
        make_plan(kind, batch)


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_word_with_no_direction_is_refused(kind: SessionKind) -> None:
    """`directions_to_ask` said `()`: the caller should have left the word out, not handed
    over a word that can never be done."""
    with pytest.raises(ValueError):
        make_plan(kind, [(JIP, [H2T]), (SAGWA, [])])


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_the_same_direction_twice_for_one_word_is_refused(kind: SessionKind) -> None:
    """It would score that (word, direction) twice in one session."""
    with pytest.raises(ValueError):
        make_plan(kind, [(JIP, [H2T, T2H, H2T])])


# ---------------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------------


def test_a_word_right_one_way_and_wrong_the_other_is_not_correct() -> None:
    """Directions given out of order, reported in `Direction` order."""
    plan = make_plan(SessionKind.REVIEW, [(JIP, [V2T, H2T])])

    run_session(plan, scored_wrong_on(JIP, V2T))
    summary = plan.summary()

    assert summary.results == (
        WordResult(
            word_id=JIP.id,
            correct=False,
            directions=(
                DirectionResult(direction=H2T, correct=True),
                DirectionResult(direction=V2T, correct=False),
            ),
        ),
    )
    assert (summary.word_count, summary.correct_count) == (1, 0)
    assert (summary.question_count, summary.correct_question_count) == (2, 1)


def test_the_summary_reports_the_scored_attempt_not_the_practice() -> None:
    """집 missed on its scored question and right on the practice: the attempt that counted."""
    plan = make_plan(SessionKind.REVIEW, [(JIP, [T2H]), (SAGWA, [H2T])])

    run_session(plan, scored_wrong_on(JIP, T2H))
    summary = plan.summary()

    assert summary.results == (
        WordResult(JIP.id, False, (DirectionResult(T2H, False),)),
        WordResult(SAGWA.id, True, (DirectionResult(H2T, True),)),
    )
    assert (summary.word_count, summary.correct_count) == (2, 1)
    assert (summary.question_count, summary.correct_question_count) == (2, 1)


@pytest.mark.parametrize("seed_value", SEEDS)
def test_the_summary_lists_the_words_in_batch_order_whatever_the_shuffle(seed_value: int) -> None:
    words = numbered_words(5)
    plan = make_plan(SessionKind.LEARN, every_direction(*words), seed_value)

    run_session(plan, always_right)

    assert [result.word_id for result in plan.summary().results] == [word.id for word in words]


def test_a_perfect_session_counts_every_word_and_every_question() -> None:
    batch: Batch = [(JIP, ALL), (SAGWA, [H2T]), (MUL, [T2H, V2H])]
    plan = make_plan(SessionKind.LEARN, batch)

    run_session(plan, always_right)
    summary = plan.summary()

    assert all(result.correct for result in summary.results)
    assert [len(result.directions) for result in summary.results] == [4, 1, 2]
    assert (summary.word_count, summary.correct_count) == (3, 3)
    assert (summary.question_count, summary.correct_question_count) == (7, 7)


def test_directions_not_yet_answered_count_as_not_correct() -> None:
    """Before the end, a word with a direction still waiting is not right yet."""
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T, T2H])])
    untouched = plan.summary()
    first = plan.next_item()
    assert first is not None and first.direction is not None
    plan.record_answer(first.number, correct=True)
    other = T2H if first.direction is H2T else H2T

    halfway = plan.summary().results[0]

    assert untouched.results[0] == WordResult(
        JIP.id, False, (DirectionResult(H2T, False), DirectionResult(T2H, False))
    )
    assert (untouched.question_count, untouched.correct_question_count) == (2, 0)
    assert halfway.correct is False
    assert DirectionResult(first.direction, True) in halfway.directions
    assert DirectionResult(other, False) in halfway.directions
    assert plan.summary().correct_question_count == 1


# ---------------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------------


def test_progress_starts_with_nothing_done() -> None:
    plan = make_plan(SessionKind.LEARN, [(JIP, [H2T, T2H]), (SAGWA, [V2T])])

    assert plan.progress() == SessionProgress(
        words_done=0, word_count=2, questions_done=0, question_count=3
    )


@pytest.mark.parametrize("seed_value", SEEDS)
def test_a_word_is_done_once_its_every_scored_question_is_recorded(seed_value: int) -> None:
    """Right or wrong, a recorded scored question counts; a pending one, a presentation and a
    practice question never do. A word is done with its last direction, not its first."""
    batch: Batch = [(JIP, [H2T, T2H, V2H]), (SAGWA, [V2T])]
    sizes = {JIP.id: 3, SAGWA.id: 1}
    plan = make_plan(SessionKind.LEARN, batch, seed_value)
    recorded: Counter[int] = Counter()
    answer = wrong_on(JIP, T2H)

    while (item := plan.next_item()) is not None:
        before = plan.progress()
        assert before.questions_done == sum(recorded.values())
        if item.kind is ItemKind.QUESTION:
            plan.record_answer(item.number, correct=answer(item))
            if item.scored:
                recorded[item.word.id] += 1
        words_done = sum(1 for word_id, size in sizes.items() if recorded[word_id] == size)
        assert plan.progress() == SessionProgress(
            words_done=words_done,
            word_count=2,
            questions_done=sum(recorded.values()),
            question_count=4,
        )

    assert plan.progress() == SessionProgress(
        words_done=2, word_count=2, questions_done=4, question_count=4
    )


def test_a_word_asked_in_two_directions_is_not_done_after_the_first() -> None:
    """The ticket's own case, stated plainly: done moves only after the second answer."""
    plan = make_plan(SessionKind.REVIEW, [(JIP, [H2T, V2T])])
    first = plan.next_item()
    assert first is not None
    plan.record_answer(first.number, correct=True)
    halfway = plan.progress()
    second = plan.next_item()
    assert second is not None
    plan.record_answer(second.number, correct=False)

    assert (halfway.words_done, halfway.questions_done) == (0, 1)
    assert (plan.progress().words_done, plan.progress().questions_done) == (1, 2)
