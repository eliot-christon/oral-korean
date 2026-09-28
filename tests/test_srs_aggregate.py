"""Tests for a word's statistics over several memories: vocab-directions T01's aggregate.

Split from `test_srs.py` (vocab-core T01's contract) only to keep both under pylint's module
length. Written before the implementation; the contract, in `oral_korean.srs.memory`:

- `aggregate_statistics(states: Sequence[MemoryState | None], at: datetime) -> WordStatistics`.
  `srs/` stays direction-agnostic: it takes any non-empty sequence (a word passes its four
  directions' memories) and raises `ValueError` on an empty one.
- `score`: the whole-percent mean of each state's `score(state)`, a `None` state counting 0,
  rounded to the nearest percent; `None` only when every state is `None`.
- `phase`: `NEW` only when every state is `None`, else `REVIEW`.
- `due`: whether any state that is not `None` is due at `at` (`at >= next_review`).
- `next_review`: the earliest among the states; `last_review`: the latest.
- `review_count` and `lapse_count`: summed.
- `recall`, `stability` and `difficulty`: always `None`, having no word-level meaning.
- Every state `None`: exactly `statistics(None, at)`, the new word's statistics.

Decision taken here that the design leaves open, flagged in the hand-back report: **a naive
`at` is refused with a `ValueError`**, as `statistics` refuses one, even when every state is
`None` (`test_srs.py`'s decision 2: a caller holding naive datetimes has a bug whichever word it
asks about first).

States come from `srs/` with fuzzing off. A state at an exact strength is `dataclasses.replace`
of a real state onto a stability found by sweeping `strength` in hundredths of a day, the way
`test_exercises_vocab.py` pins the typing threshold: FSRS figures are never invented.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest
from conftest import signature_shape

from oral_korean.srs.memory import (
    Familiarity,
    Grade,
    MemoryState,
    Phase,
    WordStatistics,
    aggregate_statistics,
    apply_grade,
    seed,
    statistics,
    strength,
)

T0 = datetime(2026, 9, 21, 9, 0, 0, tzinfo=UTC)
DAY = timedelta(days=1)
SECOND = timedelta(seconds=1)


def seeded(familiarity: Familiarity, at: datetime = T0) -> MemoryState:
    """The state `familiarity` seeds at `at`, failing loudly rather than returning `None`."""
    result = seed(familiarity, at, fuzzing=False)
    assert result is not None, f"{familiarity} must seed a memory state"
    return result[0]


def at_strength(percent: int) -> MemoryState:
    """A real state moved onto the smallest stability whose strength is `percent`."""
    stability = next(
        hundredths / 100
        for hundredths in range(1, 365_00)
        if strength(hundredths / 100) == percent
    )
    return dataclasses.replace(seeded(Familiarity.WELL), stability=stability)


def answered(state: MemoryState | None, grades: list[Grade], at: datetime) -> MemoryState:
    """`state` after `grades`, the first at `at` and each next one on the due date it set."""
    assert grades, "at least one grade"
    for grade in grades:
        state, _ = apply_grade(state, grade, at, fuzzing=False)
        at = state.next_review
    assert state is not None
    return state


# ---------------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------------


def test_the_aggregate_takes_the_states_and_the_instant() -> None:
    """Positional like `statistics(state, at)`; no direction anywhere in `srs/`."""
    function: Callable[..., object] = aggregate_statistics

    assert signature_shape(function) == (["states", "at"], [])


def test_the_aggregate_is_a_word_statistics_value() -> None:
    """The same value the word routes already serialise, so `statistics` keeps its shape."""
    stats = aggregate_statistics([seeded(Familiarity.WELL), None], T0)

    assert isinstance(stats, WordStatistics)


def test_an_empty_sequence_is_refused() -> None:
    """A word always has memories to aggregate; none at all is a caller's bug."""
    with pytest.raises(ValueError):
        aggregate_statistics([], T0)


def test_a_naive_instant_is_refused_even_with_no_memory_at_all() -> None:
    """As `statistics(None, naive)` is: the instant is checked before the states are read."""
    with pytest.raises(ValueError):
        aggregate_statistics([None, None, None, None], datetime(2026, 9, 21, 9, 0))


# ---------------------------------------------------------------------------------
# Headline score
# ---------------------------------------------------------------------------------


def test_the_score_is_the_mean_strength_a_missing_memory_counting_zero() -> None:
    """The ticket's own example: strengths 40, 40, none and 20 make 25, not 33."""
    states = [at_strength(40), at_strength(40), None, at_strength(20)]
    assert [strength(state.stability) for state in states if state] == [40, 40, 20]  # sanity

    assert aggregate_statistics(states, T0).score == 25


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        pytest.param(41, 10, id="10.25-rounds-down"),
        pytest.param(43, 11, id="10.75-rounds-up"),
    ],
)
def test_the_mean_is_rounded_to_the_nearest_whole_percent(percent: int, expected: int) -> None:
    """Neither truncated nor rounded up: a quarter of 41 is 10, a quarter of 43 is 11."""
    states = [at_strength(percent), None, None, None]

    assert aggregate_statistics(states, T0).score == expected


def test_four_equal_states_score_what_one_of_them_scores() -> None:
    """A seed lands in all four directions, so a freshly seeded word keeps its seeded score."""
    state = seeded(Familiarity.WELL)

    assert aggregate_statistics([state] * 4, T0).score == statistics(state, T0).score


def test_the_score_is_a_whole_percent() -> None:
    """The headline is an `int`, as a single state's score is."""
    score = aggregate_statistics([at_strength(40), None, at_strength(20)], T0).score

    assert isinstance(score, int)


def test_every_state_missing_is_the_new_word_statistics() -> None:
    """No memory in any direction: "New", no score, not due, nothing counted."""
    stats = aggregate_statistics([None, None, None, None], T0)

    assert stats == statistics(None, T0)
    assert stats.score is None
    assert stats.phase is Phase.NEW
    assert stats.due is False


def test_one_learned_direction_is_enough_to_leave_the_new_phase() -> None:
    """A word answered once in one direction is being reviewed, even with a low headline."""
    stats = aggregate_statistics([None, None, seeded(Familiarity.A_LITTLE), None], T0)

    assert stats.phase is Phase.REVIEW
    assert stats.score is not None


# ---------------------------------------------------------------------------------
# Dates and due
# ---------------------------------------------------------------------------------


def four_dated_states() -> list[MemoryState | None]:
    """Due a day, two days and eight days after T0, plus one direction never learned."""
    return [
        seeded(Familiarity.WELL),
        None,
        seeded(Familiarity.A_LITTLE),
        seeded(Familiarity.VERY_WELL),
    ]


def test_the_next_review_is_the_earliest_learned_one() -> None:
    """The `a_little` direction, a day after T0: the missing one has no date to offer."""
    stats = aggregate_statistics(four_dated_states(), T0)

    assert stats.next_review == seeded(Familiarity.A_LITTLE).next_review == T0 + DAY


def test_the_last_review_is_the_latest_one() -> None:
    """Three directions seeded at T0, one answered three hours later."""
    later = T0 + timedelta(hours=3)
    answered_later = answered(None, [Grade.GOOD], later)
    states = [seeded(Familiarity.WELL), answered_later, None, seeded(Familiarity.WELL)]

    assert aggregate_statistics(states, T0 + DAY).last_review == later


@pytest.mark.parametrize(
    ("offset", "due"),
    [
        pytest.param(-SECOND, False, id="a-second-before-the-earliest"),
        pytest.param(timedelta(0), True, id="exactly-at-the-earliest"),
        pytest.param(DAY, True, id="once-two-are-due"),
    ],
)
def test_the_word_is_due_as_soon_as_any_learned_direction_is(
    offset: timedelta, due: bool
) -> None:
    """Due at the earliest learned direction's next review, not a second before."""
    stats = aggregate_statistics(four_dated_states(), T0 + DAY + offset)

    assert stats.due is due


def test_a_missing_memory_never_makes_a_word_due() -> None:
    """A never-learned direction is learned, not reviewed, however late it is."""
    stats = aggregate_statistics([None, seeded(Familiarity.VERY_WELL)], T0 + DAY)

    assert stats.due is False


# ---------------------------------------------------------------------------------
# Counts and the figures with no word-level meaning
# ---------------------------------------------------------------------------------


def test_the_review_and_lapse_counts_are_summed() -> None:
    """Two answers and a lapse, one answer, a seeded miss (one answer, one lapse), and none."""
    states = [
        answered(None, [Grade.GOOD, Grade.AGAIN], T0),
        answered(None, [Grade.AGAIN], T0),
        answered(seeded(Familiarity.WELL), [Grade.AGAIN], seeded(Familiarity.WELL).next_review),
        None,
    ]
    assert [(s.review_count, s.lapse_count) for s in states if s] == [(2, 1), (1, 0), (1, 1)]

    stats = aggregate_statistics(states, T0)

    assert (stats.review_count, stats.lapse_count) == (4, 2)


@pytest.mark.parametrize(
    "states",
    [
        pytest.param([seeded(Familiarity.WELL)], id="one-state"),
        pytest.param([seeded(Familiarity.WELL)] * 4, id="four-equal-states"),
        pytest.param([seeded(Familiarity.WELL), None, None, None], id="one-learned"),
    ],
)
def test_recall_stability_and_difficulty_are_always_absent(
    states: list[MemoryState | None],
) -> None:
    """They describe one memory; averaged over directions they would describe none."""
    stats = aggregate_statistics(states, T0 + DAY)

    assert (stats.recall, stats.stability, stats.difficulty) == (None, None, None)


def test_one_state_aggregates_to_its_own_statistics_but_the_per_memory_figures() -> None:
    """Direction-agnostic: a single memory is the degenerate case, and agrees with `statistics`
    on every word-level figure."""
    state = answered(seeded(Familiarity.WELL), [Grade.GOOD, Grade.AGAIN], T0 + 2 * DAY)
    at = state.next_review + DAY

    expected = dataclasses.replace(
        statistics(state, at), recall=None, stability=None, difficulty=None
    )

    assert aggregate_statistics([state], at) == expected


def test_the_order_of_the_states_does_not_matter() -> None:
    """Directions are keys, not ranks: every ordering aggregates alike."""
    states = four_dated_states()
    at = T0 + DAY

    results = {aggregate_statistics(list(order), at) for order in permutations(states)}

    assert len(results) == 1
