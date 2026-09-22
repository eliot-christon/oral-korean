"""Tests for the FSRS memory model: seeding, grading, the score, recall and statistics.

Framing-mode note: none of the production code below exists yet. These tests are written
from vocab-core T01's acceptance criteria and test contract, and they define the contract
the implementation must satisfy. Everything is imported from `oral_korean.srs.memory`
(`oral_korean/srs/__init__.py` re-exports nothing, like `korean/`):

- `Grade` (`StrEnum`): `AGAIN`, `HARD`, `GOOD`, `EASY`, valued "again", "hard", "good",
  "easy". Declaration order is the ordering.
- `Familiarity` (`StrEnum`): `NEW`, `A_LITTLE`, `WELL`, `VERY_WELL`, valued "new",
  "a_little", "well", "very_well": the wire values T05 takes off a request.
- `Phase` (`StrEnum`): `NEW` ("new"), `REVIEW` ("review").
- `DESIRED_RETENTION = 0.9` and `STRENGTH_HORIZON_DAYS = 365`, named constants.
- `MemoryState`, frozen: `stability`, `difficulty`, `next_review`, `last_review`,
  `review_count`, `lapse_count`.
- `ReviewRecord`, frozen: `grade`, `reviewed_at`, `is_seed`, `recall_before`, `stability`,
  `difficulty`, `next_review`.
- `WordStatistics`, frozen: `score`, `recall`, `stability`, `difficulty`, `phase`,
  `next_review`, `last_review`, `due`, `review_count`, `lapse_count`.
- `seed(familiarity, at, *, fuzzing=True) -> tuple[MemoryState, ReviewRecord] | None`
- `apply_grade(state, grade, at, *, fuzzing=True) -> tuple[MemoryState, ReviewRecord]`
- `strength(stability) -> int`; `score(state) -> int | None`, which takes no instant
  because the score does not move with time; `recall(state, at) -> int | None`;
  `statistics(state, at) -> WordStatistics`.

Decisions taken here that the ticket leaves open, flagged in the hand-back report:

1. **Grades are ordered by declaration, never by `<`.** On a `StrEnum`, `<` compares the
   strings, and alphabetically "easy" < "good" < "hard". No test uses it; no caller should.
2. **A naive instant is refused everywhere**, even where the answer would not need it
   (seeding `new`, the recall or statistics of a word with no state): a caller holding naive
   datetimes has a bug whichever word it happens to ask about first.
3. **Every datetime a value carries is UTC** (offset zero), whatever offset the instant
   arrived with, so T04 can store UTC text without converting.
4. **A lapse is an Again on a word that already had a memory state.** A seed counts as
   prior knowledge, and so does an earlier answer, even one graded Again.
5. **The fuzz band is measured on the interval** from the review to the next review.

The FSRS figures below are fsrs 6.3.2's default parameters (w1 = 1.2931, w2 = 2.3065,
w3 = 8.2956). If they fail after a library upgrade, re-read the familiarity mapping with the
user; do not update the numbers blindly. The strength figures are the project's own formula
and are pinned directly.

Pure calls throughout: no patching, no file, no clock. Fuzzing is off unless a test says
otherwise, and every history starts at the reference instant `T0`.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from itertools import pairwise

import pytest
from conftest import signature_shape

from oral_korean.srs.memory import (
    DESIRED_RETENTION,
    STRENGTH_HORIZON_DAYS,
    Familiarity,
    Grade,
    MemoryState,
    Phase,
    ReviewRecord,
    WordStatistics,
    apply_grade,
    recall,
    score,
    seed,
    statistics,
    strength,
)

T0 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=UTC)
NAIVE_T0 = datetime(2026, 9, 21, 9, 0, 0)
DAY = timedelta(days=1)
SECOND = timedelta(seconds=1)

# Fifty draws of the unseedable fuzz: enough that a fuzz which never fires cannot hide.
REPETITIONS = 50

SEEDED_LEVELS = [Familiarity.A_LITTLE, Familiarity.WELL, Familiarity.VERY_WELL]
SEEDED_IDS = [level.value for level in SEEDED_LEVELS]
GRADES = list(Grade)
GRADE_IDS = [grade.value for grade in GRADES]

# Two offsets on either side of UTC. At -12:00, T0 falls on the previous calendar day, which
# is where anything that read the local date instead of the instant would go wrong.
OFFSETS = [
    pytest.param(timezone(timedelta(hours=9)), id="plus-09-00"),
    pytest.param(timezone(timedelta(hours=-12)), id="minus-12-00"),
]


def start_state(familiarity: Familiarity) -> MemoryState | None:
    """What adding a word at `familiarity` on T0 gives: a seeded state, or none for `new`."""
    result = seed(familiarity, T0, fuzzing=False)
    return None if result is None else result[0]


def seeded(familiarity: Familiarity) -> MemoryState:
    """The state `familiarity` seeds on T0.

    Fails loudly instead of returning `None`, so a test about a seeded word can never run
    quietly against a new one.
    """
    state = start_state(familiarity)
    assert state is not None, f"{familiarity} must seed a memory state"
    return state


def graded(state: MemoryState | None, grade: Grade, at: datetime) -> MemoryState:
    """`state` after `grade` answered at `at`, fuzzing off."""
    return apply_grade(state, grade, at, fuzzing=False)[0]


def on_due_date(state: MemoryState, grade: Grade) -> MemoryState:
    """`state` after `grade`, answered at the very instant it falls due."""
    return graded(state, grade, state.next_review)


def answer_in_turn(start: MemoryState | None, grades: Sequence[Grade]) -> list[MemoryState]:
    """Every state a word goes through when `grades` are answered on consecutive due dates.

    Each answer comes at the instant the previous one made the word due; a word with no
    state yet is first answered at T0.
    """
    states: list[MemoryState] = []
    state = start
    at = T0 if start is None else start.next_review
    for grade in grades:
        state = graded(state, grade, at)
        states.append(state)
        at = state.next_review
    return states


def score_of(state: MemoryState) -> int:
    """The score of a word that has a memory state, which is never absent."""
    value = score(state)
    assert value is not None, "a word with a memory state always has a score"
    return value


def recall_of(state: MemoryState, at: datetime) -> int:
    """The recall at `at` of a word that has a memory state, which is never absent."""
    value = recall(state, at)
    assert value is not None, "a word with a memory state always has a recall"
    return value


def strictly_increasing(values: Sequence[float]) -> bool:
    """True when every value is above the one before it."""
    return all(earlier < later for earlier, later in pairwise(values))


def strictly_decreasing(values: Sequence[float]) -> bool:
    """True when every value is below the one before it."""
    return all(earlier > later for earlier, later in pairwise(values))


def non_increasing(values: Sequence[float]) -> bool:
    """True when no value is above the one before it."""
    return all(earlier >= later for earlier, later in pairwise(values))


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


def test_grade_has_exactly_four_members_from_again_to_easy() -> None:
    """Four grades in the order FSRS ranks them; declaration order is the ordering.

    `<` is deliberately not used: on a `StrEnum` it compares the strings, and "easy" <
    "good" < "hard" alphabetically. vocab-sessions T02 maps answers onto these members.
    """
    assert [grade.name for grade in Grade] == ["AGAIN", "HARD", "GOOD", "EASY"]
    assert [grade.value for grade in Grade] == ["again", "hard", "good", "easy"]
    assert Grade("good") is Grade.GOOD


def test_familiarity_has_exactly_four_levels_with_their_wire_values() -> None:
    """The values are what a request carries (T05), so a rename must fail here first."""
    assert [level.name for level in Familiarity] == ["NEW", "A_LITTLE", "WELL", "VERY_WELL"]
    assert [level.value for level in Familiarity] == ["new", "a_little", "well", "very_well"]
    assert Familiarity("a_little") is Familiarity.A_LITTLE


def test_phase_is_new_or_review() -> None:
    """Two phases only: with no learning steps, a word is never "learning" in FSRS's sense."""
    assert [phase.name for phase in Phase] == ["NEW", "REVIEW"]
    assert [phase.value for phase in Phase] == ["new", "review"]


def test_the_retention_target_and_the_strength_horizon_are_named_constants() -> None:
    """Both are product choices, visible by name; the horizon is where the score reaches 100."""
    assert DESIRED_RETENTION == 0.9
    assert STRENGTH_HORIZON_DAYS == 365
    assert strength(STRENGTH_HORIZON_DAYS) == 100


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        pytest.param(seed, ["familiarity", "at"], ["fuzzing"], id="seed"),
        pytest.param(apply_grade, ["state", "grade", "at"], ["fuzzing"], id="apply_grade"),
        pytest.param(strength, ["stability"], [], id="strength"),
        pytest.param(score, ["state"], [], id="score"),
        pytest.param(recall, ["state", "at"], [], id="recall"),
        pytest.param(statistics, ["state", "at"], [], id="statistics"),
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """`score` takes no instant: that is how "the score does not move with time" is built in.

    `fuzzing` is keyword-only, so a stray positional `False` cannot switch it off unseen.
    """
    assert signature_shape(function) == (positional, keyword_only)


@pytest.mark.parametrize("function", [seed, apply_grade], ids=["seed", "apply_grade"])
def test_fuzzing_is_on_unless_the_caller_turns_it_off(function: Callable[..., object]) -> None:
    """Production spreads reviews out; only deterministic callers and tests opt out."""
    assert inspect.signature(function).parameters["fuzzing"].default is True


def test_a_memory_state_is_a_frozen_value_with_the_agreed_fields() -> None:
    """T04 persists these fields, and a mutable state could change under its history."""
    state = seeded(Familiarity.WELL)
    names = [field.name for field in dataclasses.fields(state)]

    assert isinstance(state, MemoryState)
    assert names == [
        "stability",
        "difficulty",
        "next_review",
        "last_review",
        "review_count",
        "lapse_count",
    ]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(state, name, None)


def test_a_review_record_is_a_frozen_value_with_the_agreed_fields() -> None:
    """One history entry, as the word-detail view will list it."""
    _, record = apply_grade(None, Grade.GOOD, T0, fuzzing=False)
    names = [field.name for field in dataclasses.fields(record)]

    assert isinstance(record, ReviewRecord)
    assert names == [
        "grade",
        "reviewed_at",
        "is_seed",
        "recall_before",
        "stability",
        "difficulty",
        "next_review",
    ]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, name, None)


def test_word_statistics_are_a_frozen_value_with_the_agreed_fields() -> None:
    """Everything FSRS knows about a word, as T05 will serialise it."""
    stats = statistics(seeded(Familiarity.WELL), T0)
    names = [field.name for field in dataclasses.fields(stats)]

    assert isinstance(stats, WordStatistics)
    assert names == [
        "score",
        "recall",
        "stability",
        "difficulty",
        "phase",
        "next_review",
        "last_review",
        "due",
        "review_count",
        "lapse_count",
    ]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(stats, name, None)


# ---------------------------------------------------------------------------------
# Familiarity seeding
# ---------------------------------------------------------------------------------


def test_seeding_a_new_word_gives_no_state_and_no_record() -> None:
    """`new` means nothing is known yet: no state, no history entry, "New" rather than 0%."""
    assert seed(Familiarity.NEW, T0, fuzzing=False) is None


@pytest.mark.parametrize(
    ("familiarity", "stability", "days", "grade"),
    [
        pytest.param(Familiarity.A_LITTLE, 1.29, 1, Grade.HARD, id="a_little"),
        pytest.param(Familiarity.WELL, 2.31, 2, Grade.GOOD, id="well"),
        pytest.param(Familiarity.VERY_WELL, 8.30, 8, Grade.EASY, id="very_well"),
    ],
)
def test_seeding_is_a_synthetic_first_review_at_the_moment_of_adding(
    familiarity: Familiarity, stability: float, days: int, grade: Grade
) -> None:
    """The epic's familiarity table: FSRS's own initial stabilities, not invented constants.

    The seed record is what lets the user see why a word they never answered has a score.
    """
    result = seed(familiarity, T0, fuzzing=False)

    assert result is not None
    state, record = result
    assert state.stability == pytest.approx(stability, abs=0.01)
    assert state.next_review == T0 + days * DAY
    assert state.last_review == T0
    assert record.grade is grade
    assert record.is_seed is True
    assert record.reviewed_at == T0
    assert record.recall_before is None
    assert (record.stability, record.difficulty, record.next_review) == (
        state.stability,
        state.difficulty,
        state.next_review,
    )


@pytest.mark.parametrize(
    ("familiarity", "grade"),
    [
        (Familiarity.A_LITTLE, Grade.HARD),
        (Familiarity.WELL, Grade.GOOD),
        (Familiarity.VERY_WELL, Grade.EASY),
    ],
    ids=SEEDED_IDS,
)
def test_a_seed_is_the_state_a_first_answer_of_that_grade_produces(
    familiarity: Familiarity, grade: Grade
) -> None:
    """Same scheduler, same figures; only the review count tells a seed from an answer."""
    seeded_state = seeded(familiarity)
    answered = graded(None, grade, T0)

    assert (
        seeded_state.stability,
        seeded_state.difficulty,
        seeded_state.next_review,
        seeded_state.last_review,
    ) == (answered.stability, answered.difficulty, answered.next_review, answered.last_review)
    assert (seeded_state.review_count, answered.review_count) == (0, 1)


def test_the_seeded_levels_are_strictly_ordered() -> None:
    """"Very well" must never start weaker, sooner or lower than "a little"."""
    states = [seeded(level) for level in SEEDED_LEVELS]
    next_reviews = [state.next_review for state in states]

    assert strictly_increasing([state.stability for state in states])
    assert all(earlier < later for earlier, later in pairwise(next_reviews))
    assert strictly_increasing([score_of(state) for state in states])


@pytest.mark.parametrize(
    ("familiarity", "expected_score"),
    [
        pytest.param(Familiarity.A_LITTLE, 14, id="a_little"),
        pytest.param(Familiarity.WELL, 20, id="well"),
        pytest.param(Familiarity.VERY_WELL, 38, id="very_well"),
    ],
)
def test_a_freshly_seeded_word_has_its_starting_score_and_full_recall(
    familiarity: Familiarity, expected_score: int
) -> None:
    """The starting scores the epic promises the user, and recall 100 at the moment of adding."""
    state = seeded(familiarity)

    assert score(state) == expected_score
    assert recall(state, T0) == 100


@pytest.mark.parametrize("familiarity", SEEDED_LEVELS, ids=SEEDED_IDS)
def test_a_seed_is_not_a_review(familiarity: Familiarity) -> None:
    """Seeds are left out of the counts, yet a seeded word is not new: review sessions serve it."""
    state = seeded(familiarity)
    stats = statistics(state, T0)

    assert (state.review_count, state.lapse_count) == (0, 0)
    assert (stats.review_count, stats.lapse_count) == (0, 0)
    assert stats.phase is Phase.REVIEW


def test_only_a_seed_record_is_flagged_as_a_seed() -> None:
    """Answers, a new word's first included, are never mistaken for seeds in the history."""
    result = seed(Familiarity.WELL, T0, fuzzing=False)
    assert result is not None
    state, seed_record = result

    _, answer_record = apply_grade(state, Grade.GOOD, state.next_review, fuzzing=False)
    _, first_answer_record = apply_grade(None, Grade.GOOD, T0, fuzzing=False)

    assert seed_record.is_seed is True
    assert answer_record.is_seed is False
    assert first_answer_record.is_seed is False


# ---------------------------------------------------------------------------------
# Applying grades
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grade", "stability", "days"),
    [
        pytest.param(Grade.HARD, 1.29, 1, id="hard"),
        pytest.param(Grade.GOOD, 2.31, 2, id="good"),
        pytest.param(Grade.EASY, 8.30, 8, id="easy"),
    ],
)
def test_a_new_words_first_right_answer_graduates_at_once(
    grade: Grade, stability: float, days: int
) -> None:
    """No learning steps: a first answer goes straight to the review phase, days away.

    Good and easy are here as well as the ticket's hard, because they are what proves each
    grade reaches the library as the rating of the same name.
    """
    state = graded(None, grade, T0)

    assert state.stability == pytest.approx(stability, abs=0.01)
    assert state.next_review == T0 + days * DAY
    assert statistics(state, T0).phase is Phase.REVIEW


def test_a_new_words_first_miss_comes_back_a_day_later_never_minutes() -> None:
    """With the library's default steps, Again would bring the word back one minute later."""
    missed = graded(None, Grade.AGAIN, T0)
    hard = graded(None, Grade.HARD, T0)

    assert missed.next_review == T0 + DAY
    assert missed.stability < hard.stability
    assert statistics(missed, T0).phase is Phase.REVIEW


def test_hard_on_five_consecutive_due_dates_keeps_growing() -> None:
    """The no-learning-step trap: the regression test for the deadlock found while scoping.

    With the library's default learning steps, Hard never advances a step: the word stays
    in learning, comes back minutes later, and its stability sits at 1.29 days forever. The
    figures are the ticket's "about", to a tenth of a day.
    """
    states = answer_in_turn(None, [Grade.HARD] * 5)
    stabilities = [state.stability for state in states]

    assert strictly_increasing(stabilities)
    assert stabilities == pytest.approx([1.3, 3.2, 6.7, 11.9, 18.2], abs=0.1)
    assert min(state.next_review - state.last_review for state in states) >= DAY


@pytest.mark.parametrize(
    "start", [Familiarity.NEW, Familiarity.WELL], ids=["new-word", "seeded-well"]
)
def test_again_on_five_consecutive_due_dates_keeps_shrinking_a_day_at_a_time(
    start: Familiarity,
) -> None:
    """Repeated misses weaken the word every time, and never schedule it sooner than a day.

    In-session repetition is the session's job (vocab-sessions), not the scheduler's.
    """
    states = answer_in_turn(start_state(start), [Grade.AGAIN] * 5)

    assert strictly_decreasing([state.stability for state in states])
    assert [state.next_review - state.last_review for state in states] == [DAY] * 5


def test_from_the_same_due_state_good_grows_more_than_hard_and_again_shrinks() -> None:
    """The grades mean what they say, from one shared starting point."""
    known = seeded(Familiarity.WELL)

    hard = on_due_date(known, Grade.HARD)
    good = on_due_date(known, Grade.GOOD)
    missed = on_due_date(known, Grade.AGAIN)

    assert good.stability > hard.stability > known.stability > missed.stability


def test_the_record_of_a_new_words_first_answer_has_no_recall_before() -> None:
    """Nothing was known, so nothing was predicted: absent, not 0."""
    state, record = apply_grade(None, Grade.GOOD, T0, fuzzing=False)

    assert record.grade is Grade.GOOD
    assert record.reviewed_at == T0
    assert record.is_seed is False
    assert record.recall_before is None
    assert (record.stability, record.difficulty, record.next_review) == (
        state.stability,
        state.difficulty,
        state.next_review,
    )


@pytest.mark.parametrize("grade", GRADES, ids=GRADE_IDS)
def test_the_record_of_a_known_words_answer_carries_the_recall_just_before(grade: Grade) -> None:
    """The history shows what FSRS predicted at the moment of answering, then what followed.

    The predicted recall is the word's recall at that instant, as a fraction in (0, 1].
    """
    known = seeded(Familiarity.WELL)
    at = known.next_review

    state, record = apply_grade(known, grade, at, fuzzing=False)

    assert record.grade is grade
    assert record.reviewed_at == at
    assert record.is_seed is False
    assert record.recall_before is not None
    assert 0 < record.recall_before <= 1
    assert round(100 * record.recall_before) == recall(known, at)
    assert (record.stability, record.difficulty, record.next_review) == (
        state.stability,
        state.difficulty,
        state.next_review,
    )


@pytest.mark.parametrize("grade", GRADES, ids=GRADE_IDS)
def test_applying_a_grade_leaves_the_input_state_as_it_was(grade: Grade) -> None:
    """A new state comes back; the one passed in, which T04 may still hold, is untouched."""
    known = seeded(Familiarity.WELL)
    untouched = dataclasses.replace(known)

    after, _ = apply_grade(known, grade, known.next_review, fuzzing=False)

    assert known == untouched
    assert after != known


@pytest.mark.parametrize(
    "delay",
    [pytest.param(timedelta(0), id="same-instant"), pytest.param(timedelta(hours=3), id="3h")],
)
def test_a_second_review_on_the_same_day_is_accepted_and_deterministic(delay: timedelta) -> None:
    """A word answered twice in one day (added, then quizzed at once) is not an error.

    Fuzzing off, the same input gives the same output: nothing hidden varies between calls.
    """
    first = graded(None, Grade.GOOD, T0)
    again_today = T0 + delay

    once = apply_grade(first, Grade.GOOD, again_today, fuzzing=False)
    twice = apply_grade(first, Grade.GOOD, again_today, fuzzing=False)

    assert once == twice
    state, record = once
    assert state.last_review == again_today
    assert state.next_review > again_today
    assert state.review_count == 2
    assert record.reviewed_at == again_today
    assert record.recall_before is not None
    assert 0 < record.recall_before <= 1


# ---------------------------------------------------------------------------------
# Score (strength)
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stability", "expected"),
    [
        pytest.param(1.29, 14, id="1.29-days"),
        pytest.param(2.31, 20, id="2.31-days"),
        pytest.param(8.30, 38, id="8.30-days"),
        pytest.param(23, 54, id="23-days"),
        pytest.param(120, 81, id="120-days"),
        pytest.param(365, 100, id="365-days"),
        pytest.param(1000, 100, id="1000-days-capped"),
    ],
)
def test_the_strength_of_a_stability(stability: float, expected: int) -> None:
    """The project's own formula over a one-year horizon: a whole percent, capped at 100."""
    result = strength(stability)

    assert result == expected
    assert isinstance(result, int)


def test_strength_never_decreases_and_stays_between_0_and_100() -> None:
    """Swept from 0.1 to 1000 days, a tenth of a day at a time."""
    strengths = [strength(tenths / 10) for tenths in range(1, 10_001)]

    assert strengths == sorted(strengths)
    assert min(strengths) >= 0
    assert max(strengths) == 100


def test_a_word_with_no_memory_state_has_no_score() -> None:
    """A new word reads "New", never 0%."""
    assert score(None) is None


@pytest.mark.parametrize("start", SEEDED_LEVELS, ids=SEEDED_IDS)
@pytest.mark.parametrize("grade", GRADES, ids=GRADE_IDS)
def test_the_score_is_the_strength_of_the_stability(start: Familiarity, grade: Grade) -> None:
    """Whatever the history, the score is read off stability and nothing else."""
    state = on_due_date(seeded(start), grade)

    assert score(state) == strength(state.stability)


def test_the_score_does_not_move_with_time() -> None:
    """Only an answer moves the score; recall is the figure that drifts in between."""
    state = seeded(Familiarity.WELL)
    instants = [T0, T0 + DAY, T0 + 7 * DAY, T0 + 30 * DAY]

    assert [statistics(state, at).score for at in instants] == [20, 20, 20, 20]
    assert recall_of(state, instants[-1]) < recall_of(state, instants[0])


def test_the_score_rises_after_a_right_answer() -> None:
    """Up after hard, further up after good, from the same state on its due date."""
    known = seeded(Familiarity.WELL)

    before = score_of(known)
    after_hard = score_of(on_due_date(known, Grade.HARD))
    after_good = score_of(on_due_date(known, Grade.GOOD))

    assert before < after_hard < after_good


def test_the_score_drops_at_once_after_a_miss() -> None:
    """The reason the score is strength and not recall: a miss shows immediately.

    Seeded very well, answered good on its due date (stability about 39 days), then missed
    on the next due date: lower at that same instant, not a day later.
    """
    known = on_due_date(seeded(Familiarity.VERY_WELL), Grade.GOOD)
    miss_at = known.next_review
    missed = graded(known, Grade.AGAIN, miss_at)

    before = statistics(known, miss_at).score
    after = statistics(missed, miss_at).score

    assert known.stability == pytest.approx(39, abs=0.5)
    assert before is not None
    assert after is not None
    assert after < before


def test_the_score_never_rises_over_five_misses_in_a_row() -> None:
    """Starting from a seeded score, five misses on consecutive due dates only bring it down."""
    known = seeded(Familiarity.WELL)
    states = answer_in_turn(known, [Grade.AGAIN] * 5)

    assert non_increasing([score_of(known), *(score_of(state) for state in states)])


# ---------------------------------------------------------------------------------
# Recall (retrievability)
# ---------------------------------------------------------------------------------


def test_a_word_with_no_memory_state_has_no_recall() -> None:
    """Absent, not 0: the library's 0 for a never-reviewed card must not leak through."""
    assert recall(None, T0) is None


@pytest.mark.parametrize("grade", GRADES, ids=GRADE_IDS)
@pytest.mark.parametrize(
    "start", [Familiarity.NEW, Familiarity.WELL], ids=["new-word", "seeded-well"]
)
def test_recall_is_100_right_after_any_review_even_a_miss(start: Familiarity, grade: Grade) -> None:
    """FSRS's definition, pinned so nobody "fixes" it and the UI never claims otherwise."""
    before = start_state(start)
    at = T0 if before is None else before.next_review

    after = graded(before, grade, at)

    assert recall(after, at) == 100


def test_recall_counts_whole_days_since_the_last_review() -> None:
    """Still 100 after 23 hours, below it after 25: the library counts whole days."""
    state = graded(None, Grade.GOOD, T0)

    after_a_day = recall(state, T0 + timedelta(hours=25))

    assert recall(state, T0 + timedelta(hours=23)) == 100
    assert isinstance(after_a_day, int)
    assert after_a_day < 100


def test_recall_decays_between_reviews() -> None:
    """Seeded well: never higher later, and clearly lower after a month than after two days."""
    state = seeded(Familiarity.WELL)
    recalls = [recall_of(state, T0 + days * DAY) for days in (1, 2, 7, 30)]

    assert non_increasing(recalls)
    assert recalls[3] < recalls[1]


@pytest.mark.parametrize("familiarity", SEEDED_LEVELS, ids=SEEDED_IDS)
def test_a_word_falls_due_when_its_recall_reaches_the_target(familiarity: Familiarity) -> None:
    """At its next review a word is predicted near the 90% target, whole days allowing."""
    state = seeded(familiarity)

    assert 88 <= recall_of(state, state.next_review) <= 93


def test_a_miss_leaves_a_lower_recall_than_a_right_answer() -> None:
    """Same history but the last grade: three days on, the missed word is likelier forgotten."""
    known = seeded(Familiarity.WELL)
    at = known.next_review
    later = at + 3 * DAY

    right = graded(known, Grade.GOOD, at)
    missed = graded(known, Grade.AGAIN, at)

    assert recall_of(missed, later) < recall_of(right, later)


# ---------------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------------


def test_a_new_word_has_no_figures_and_is_not_due() -> None:
    """New words are served by learn sessions, so a new word is never "due"."""
    assert statistics(None, T0) == WordStatistics(
        score=None,
        recall=None,
        stability=None,
        difficulty=None,
        phase=Phase.NEW,
        next_review=None,
        last_review=None,
        due=False,
        review_count=0,
        lapse_count=0,
    )


def test_statistics_report_the_words_own_figures() -> None:
    """Every figure is the state's own, and recall is taken at the instant asked about."""
    state = answer_in_turn(None, [Grade.GOOD, Grade.AGAIN, Grade.GOOD])[-1]
    at = state.next_review + 5 * DAY

    stats = statistics(state, at)

    assert stats == WordStatistics(
        score=score(state),
        recall=recall(state, at),
        stability=state.stability,
        difficulty=state.difficulty,
        phase=Phase.REVIEW,
        next_review=state.next_review,
        last_review=state.last_review,
        due=True,
        review_count=3,
        lapse_count=1,
    )
    assert stats.recall is not None
    assert stats.recall < 100


@pytest.mark.parametrize(
    ("start", "grades", "reviews", "lapses"),
    [
        pytest.param(Familiarity.NEW, [Grade.AGAIN], 1, 0, id="new-word-first-answer-again"),
        pytest.param(Familiarity.NEW, [Grade.GOOD, Grade.AGAIN], 2, 1, id="reviewed-then-again"),
        pytest.param(Familiarity.NEW, [Grade.AGAIN, Grade.AGAIN], 2, 1, id="missed-twice"),
        pytest.param(
            Familiarity.NEW,
            [Grade.GOOD, Grade.HARD, Grade.GOOD, Grade.EASY],
            4,
            0,
            id="never-missed",
        ),
        pytest.param(
            Familiarity.NEW,
            [Grade.GOOD, Grade.AGAIN, Grade.HARD, Grade.AGAIN, Grade.EASY],
            5,
            2,
            id="two-misses",
        ),
        pytest.param(Familiarity.WELL, [Grade.AGAIN], 1, 1, id="seeded-first-answer-again"),
        pytest.param(Familiarity.VERY_WELL, [Grade.GOOD], 1, 0, id="seeded-first-answer-good"),
    ],
)
def test_reviews_count_every_answer_and_lapses_count_misses_of_a_known_word(
    start: Familiarity, grades: list[Grade], reviews: int, lapses: int
) -> None:
    """Seeds are not answers. A lapse is a miss once something was known: a seed stands for
    prior knowledge, while a new word's first miss forgot nothing.
    """
    state = answer_in_turn(start_state(start), grades)[-1]

    stats = statistics(state, state.last_review)

    assert (stats.review_count, stats.lapse_count) == (reviews, lapses)
    assert (state.review_count, state.lapse_count) == (reviews, lapses)


def test_a_word_falls_due_at_its_next_review_not_a_second_before() -> None:
    """Due means the next review has been reached, and it stays due until answered."""
    state = seeded(Familiarity.A_LITTLE)

    assert statistics(state, state.next_review - SECOND).due is False
    assert statistics(state, state.next_review).due is True
    assert statistics(state, state.next_review + 30 * DAY).due is True


# ---------------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda at: seed(Familiarity.WELL, at, fuzzing=False), id="seed"),
        pytest.param(lambda at: seed(Familiarity.NEW, at, fuzzing=False), id="seed-new"),
        pytest.param(
            lambda at: apply_grade(None, Grade.GOOD, at, fuzzing=False), id="apply-grade-new-word"
        ),
        pytest.param(
            lambda at: apply_grade(seeded(Familiarity.WELL), Grade.GOOD, at, fuzzing=False),
            id="apply-grade-known-word",
        ),
        pytest.param(lambda at: recall(seeded(Familiarity.WELL), at), id="recall"),
        pytest.param(lambda at: recall(None, at), id="recall-new-word"),
        pytest.param(lambda at: statistics(seeded(Familiarity.WELL), at), id="statistics"),
        pytest.param(lambda at: statistics(None, at), id="statistics-new-word"),
    ],
)
def test_a_naive_instant_is_refused_with_a_message_that_says_so(
    call: Callable[[datetime], object],
) -> None:
    """A naive datetime is an instant nobody can place, so it is refused, not guessed at.

    Refused by the package itself, before the library sees it, and even where the answer
    would not need the instant: a caller with naive datetimes has a bug whichever word it
    asks about first. The library's own reaction differs by call (a `TypeError` from recall),
    which is why the check cannot be left to it.
    """
    with pytest.raises(ValueError) as excinfo:
        call(NAIVE_T0)

    assert "aware" in str(excinfo.value).lower()


@pytest.mark.parametrize("zone", OFFSETS)
def test_seeding_at_another_offset_is_the_same_instant(zone: tzinfo) -> None:
    """18:00 in Seoul is 09:00 UTC: the same seed, whatever clock the caller reads."""
    assert seed(Familiarity.WELL, T0.astimezone(zone), fuzzing=False) == seed(
        Familiarity.WELL, T0, fuzzing=False
    )


@pytest.mark.parametrize("zone", OFFSETS)
def test_grading_at_another_offset_is_the_same_instant(zone: tzinfo) -> None:
    """The library refuses anything but UTC, so the package converts rather than passes it on."""
    known = seeded(Familiarity.WELL)
    due = known.next_review

    assert apply_grade(known, Grade.GOOD, due.astimezone(zone), fuzzing=False) == apply_grade(
        known, Grade.GOOD, due, fuzzing=False
    )


@pytest.mark.parametrize("zone", OFFSETS)
def test_recall_and_statistics_at_another_offset_are_the_same_instant(zone: tzinfo) -> None:
    """Reading a word's figures is as offset-blind as changing them."""
    state = seeded(Familiarity.WELL)
    at = T0 + 3 * DAY + timedelta(hours=5)

    assert recall(state, at.astimezone(zone)) == recall(state, at)
    assert statistics(state, at.astimezone(zone)) == statistics(state, at)


@pytest.mark.parametrize("zone", OFFSETS)
def test_every_datetime_a_value_carries_is_utc(zone: tzinfo) -> None:
    """Whatever offset came in, UTC comes out, so storage never has to convert (T04)."""
    result = seed(Familiarity.WELL, T0.astimezone(zone), fuzzing=False)
    assert result is not None
    state, seed_record = result
    next_due = state.next_review.astimezone(zone)
    later, record = apply_grade(state, Grade.GOOD, next_due, fuzzing=False)

    carried = [
        state.next_review,
        state.last_review,
        seed_record.reviewed_at,
        seed_record.next_review,
        later.next_review,
        later.last_review,
        record.reviewed_at,
        record.next_review,
    ]

    assert [moment.utcoffset() for moment in carried] == [timedelta(0)] * len(carried)


# ---------------------------------------------------------------------------------
# Fuzzing
# ---------------------------------------------------------------------------------


def test_fuzzing_moves_a_long_interval_within_a_quarter_of_it() -> None:
    """On by default: the next review drifts, loosely bounded, and only the date moves.

    The unfuzzed interval (seeded very well, then good on its due date) is 39 days. The
    band is a loose quarter of it rather than the library's own fuzz ranges, which are not
    copied here. Fifty draws that all land exactly on day 39 would mean fuzzing never ran.
    The stability, and so the score, must not be fuzzed.
    """
    known = seeded(Familiarity.VERY_WELL)
    due = known.next_review
    unfuzzed, _ = apply_grade(known, Grade.GOOD, due, fuzzing=False)
    unfuzzed_interval = unfuzzed.next_review - due

    fuzzed = [apply_grade(known, Grade.GOOD, due)[0] for _ in range(REPETITIONS)]
    intervals = [state.next_review - due for state in fuzzed]

    assert unfuzzed_interval == 39 * DAY
    assert [gap for gap in intervals if abs(gap - unfuzzed_interval) > unfuzzed_interval / 4] == []
    assert any(gap != unfuzzed_interval for gap in intervals)
    assert {state.stability for state in fuzzed} == {unfuzzed.stability}


def test_without_fuzzing_the_next_review_lands_exactly_on_the_interval_every_time() -> None:
    """Fuzzing off is what makes every other figure in this file reproducible."""
    known = seeded(Familiarity.VERY_WELL)
    due = known.next_review

    results = [apply_grade(known, Grade.GOOD, due, fuzzing=False) for _ in range(REPETITIONS)]

    assert all(result == results[0] for result in results)
    assert results[0][0].next_review == due + 39 * DAY
