"""A word's memory, modelled with FSRS: seeding, grading, the score and the statistics.

This is the only module in the project that knows FSRS exists, as `tts/melo_engine.py` is
for MeloTTS. It converts to and from the project's own frozen values (a grade, a
familiarity level, a memory state, a review record), so no caller ever handles an
`fsrs.Card`. py-fsrs changed its API incompatibly twice in 2025 (5.0 and 6.0); containing
it here keeps the next upgrade a one-module change. There is no Protocol and no second
scheduler: one library, one module.

The scheduler runs with **no learning steps and no relearning steps**, so every answer,
a new word's first included, schedules the word whole days ahead. With the library's
default steps, the grade mapping the vocabulary sessions need deadlocks: a correct
multiple-choice answer graded `Hard` never advances a learning step, and the word comes
back minutes later forever. Asking a missed word again within a session is the session's
job, not the scheduler's.

**The score is strength, not recall** (decided by the user, vocab-core epic). It is read
off FSRS stability on a logarithmic scale, so it moves only when the word is answered: up
after a right answer, down at once after a miss, flat in between. Recall (FSRS
retrievability) is a separate statistic, and it behaves in a way that surprises: the
library counts **whole days** since the last review, so recall reads 100% for the 24 hours
after any review, a missed one included, and only then decays. That is why it is not the
headline.

Every instant must be timezone-aware. The library accepts nothing but `timezone.utc`
itself, so aware instants at any offset are converted here, and naive ones are refused
with a message that says so rather than guessed at.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from fsrs import Card, Rating, Scheduler, State


class Grade(StrEnum):
    """How well an answer went, from a miss to effortless.

    Declaration order is the ranking. Never compare grades with `<`: on a `StrEnum` it
    compares the strings, and alphabetically "easy" sorts before "hard".
    """

    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class Familiarity(StrEnum):
    """How well the user says they already know a word when adding it.

    Anything but `NEW` seeds the word with a synthetic first review (see `seed`), so a word
    the user half knows starts with a score instead of from nothing.
    """

    NEW = "new"
    A_LITTLE = "a_little"
    WELL = "well"
    VERY_WELL = "very_well"


class Phase(StrEnum):
    """Where a word stands: never reviewed, or scheduled for review.

    Only two, because with no learning steps FSRS never keeps a word "learning".
    """

    NEW = "new"
    REVIEW = "review"


DESIRED_RETENTION: Final = 0.9
"""The recall chance at which a word falls due: FSRS's default, and not a user setting."""

STRENGTH_HORIZON_DAYS: Final = 365
"""The stability that counts as fully known: a score of 100.

A product choice, not an FSRS fact. A shorter horizon would raise every score.
"""

_CARD_ID: Final = 0
"""The id every card is built with. Nothing reads it, but without one the library derives
an id from the clock and sleeps a millisecond to keep it unique."""

_RATINGS: Final[dict[Grade, Rating]] = {
    Grade.AGAIN: Rating.Again,
    Grade.HARD: Rating.Hard,
    Grade.GOOD: Rating.Good,
    Grade.EASY: Rating.Easy,
}

_SEED_GRADES: Final[dict[Familiarity, Grade]] = {
    Familiarity.A_LITTLE: Grade.HARD,
    Familiarity.WELL: Grade.GOOD,
    Familiarity.VERY_WELL: Grade.EASY,
}
"""The grade of the synthetic first review each familiarity level stands for.

A seed is a first review rather than a hand-picked stability, so its figures are FSRS's own
initial parameters and the history can show where a never-answered word's score came from.
"""


@dataclass(frozen=True)
class MemoryState:
    """What FSRS knows about a word that has been seeded or answered at least once.

    A word with no memory state at all is new. The counts are the project's own: FSRS keeps
    neither.

    Attributes:
        stability: days until the predicted recall falls to 90%; the score is read off it.
        difficulty: how hard FSRS thinks the word is for this user, from 1 to 10.
        next_review: when the word falls due, in UTC.
        last_review: when it was last seeded or answered, in UTC.
        review_count: answers counted; a seed is not an answer.
        lapse_count: misses of a word already known. A seed counts as knowing it, so a
            seeded word missed at its first check has lapsed; a new word's first miss has not.
    """

    stability: float
    difficulty: float
    next_review: datetime
    last_review: datetime
    review_count: int
    lapse_count: int


@dataclass(frozen=True)
class ReviewRecord:
    """One entry in a word's history: a seed or an answer, and what followed it.

    Attributes:
        grade: the grade applied.
        reviewed_at: when, in UTC.
        is_seed: true for the synthetic first review made when the word was added.
        recall_before: the predicted recall just before, as a fraction in (0, 1]; `None`
            when the word had no memory state yet, which is always the case for a seed.
        stability: the stability after.
        difficulty: the difficulty after.
        next_review: when the word falls due after, in UTC.
    """

    grade: Grade
    reviewed_at: datetime
    is_seed: bool
    recall_before: float | None
    stability: float
    difficulty: float
    next_review: datetime


# One field per statistic the user reads (the epic's transparency table), so the count is
# the feature rather than a class doing too much.
@dataclass(frozen=True)
class WordStatistics:  # pylint: disable=too-many-instance-attributes
    """Everything known about a word at one instant, for the user to read.

    Every figure but the phase, `due` and the counts is `None` for a new word: a new word
    reads "New", never 0%.

    Attributes:
        score: the strength, a whole percent (see `strength`).
        recall: the predicted chance of recalling the word now, a whole percent.
        stability: in days.
        difficulty: from 1 to 10.
        phase: new or review.
        next_review: when the word falls due.
        last_review: when it was last seeded or answered.
        due: whether the next review has been reached. A new word is never due: it is
            learned, not reviewed.
        review_count: answers counted, seeds excluded.
        lapse_count: misses of a word already known.
    """

    score: int | None
    recall: int | None
    stability: float | None
    difficulty: float | None
    phase: Phase
    next_review: datetime | None
    last_review: datetime | None
    due: bool
    review_count: int
    lapse_count: int


_NEW_WORD_STATISTICS: Final = WordStatistics(
    score=None, recall=None, stability=None, difficulty=None, phase=Phase.NEW,
    next_review=None, last_review=None, due=False, review_count=0, lapse_count=0,
)
"""A new word's statistics, the same at every instant: nothing known, nothing due."""


def seed(
    familiarity: Familiarity, at: datetime, *, fuzzing: bool = True
) -> tuple[MemoryState, ReviewRecord] | None:
    """The memory state and seed record for a word added at `at` with `familiarity`.

    `NEW` seeds nothing and returns `None`. The other levels return what a first review
    graded hard, good or easy would produce, with the record flagged as a seed and the
    review count left at 0: the seed stands for knowledge the user brought, not an answer.

    Raises:
        ValueError: `at` is naive.
    """
    at = _as_utc(at)
    grade = _SEED_GRADES.get(familiarity)
    if grade is None:
        return None
    return _review(None, grade, at, fuzzing=fuzzing, is_seed=True)


def apply_grade(
    state: MemoryState | None, grade: Grade, at: datetime, *, fuzzing: bool = True
) -> tuple[MemoryState, ReviewRecord]:
    """The state after answering a word, graded `grade` at `at`, and the record of it.

    `state` is `None` for a new word. It is never modified: a new value comes back.

    Raises:
        ValueError: `at`, or a datetime in `state`, is naive.
    """
    return _review(state, grade, _as_utc(at), fuzzing=fuzzing, is_seed=False)


def strength(stability: float) -> int:
    """A stability in days as a whole percent: logarithmic, capped at the horizon.

    Logarithmic so early progress shows: 1.3 days of stability is 14%, 9 days 39%, 23 days
    54%, 120 days 81%, and `STRENGTH_HORIZON_DAYS` or more is 100%.
    """
    ratio = math.log1p(stability) / math.log1p(STRENGTH_HORIZON_DAYS)
    return min(100, round(100 * ratio))


def score(state: MemoryState | None) -> int | None:
    """A word's score: the strength of its stability, or `None` for a new word.

    It takes no instant on purpose: the score moves when the word is answered, never with
    the passing of time.
    """
    return None if state is None else strength(state.stability)


def recall(state: MemoryState | None, at: datetime) -> int | None:
    """The predicted chance of recalling the word at `at`, as a whole percent.

    `None` for a new word, where the library would say 0. 100 for the 24 hours after any
    review, because the library counts whole days since the last one.

    Raises:
        ValueError: `at`, or a datetime in `state`, is naive.
    """
    at = _as_utc(at)
    if state is None:
        return None
    return round(100 * _scheduler(fuzzing=False).get_card_retrievability(_card(state), at))


def statistics(state: MemoryState | None, at: datetime) -> WordStatistics:
    """Everything known about a word at `at`.

    Raises:
        ValueError: `at`, or a datetime in `state`, is naive.
    """
    at = _as_utc(at)
    if state is None:
        return _NEW_WORD_STATISTICS
    return WordStatistics(
        score=score(state), recall=recall(state, at),
        stability=state.stability, difficulty=state.difficulty, phase=Phase.REVIEW,
        next_review=state.next_review, last_review=state.last_review,
        due=at >= state.next_review,
        review_count=state.review_count, lapse_count=state.lapse_count,
    )


def _review(
    state: MemoryState | None, grade: Grade, at: datetime, *, fuzzing: bool, is_seed: bool
) -> tuple[MemoryState, ReviewRecord]:
    """Apply `grade` at `at` (already UTC) through the library, and count it unless a seed."""
    scheduler = _scheduler(fuzzing=fuzzing)
    card = _card(state)
    recall_before = None if state is None else scheduler.get_card_retrievability(card, at)

    reviewed, _ = scheduler.review_card(card, _RATINGS[grade], review_datetime=at)
    if reviewed.stability is None or reviewed.difficulty is None:
        # The library sets both on every review; this narrows the types and says so.
        raise RuntimeError("fsrs returned a reviewed card with no stability or difficulty")

    reviews = 0 if state is None else state.review_count
    lapses = 0 if state is None else state.lapse_count
    lapsed = state is not None and grade is Grade.AGAIN
    after = MemoryState(
        stability=reviewed.stability,
        difficulty=reviewed.difficulty,
        next_review=reviewed.due,
        last_review=at,
        review_count=reviews if is_seed else reviews + 1,
        lapse_count=lapses + 1 if lapsed else lapses,
    )
    record = ReviewRecord(
        grade=grade,
        reviewed_at=at,
        is_seed=is_seed,
        recall_before=recall_before,
        stability=after.stability,
        difficulty=after.difficulty,
        next_review=after.next_review,
    )
    return after, record


def _scheduler(*, fuzzing: bool) -> Scheduler:
    """The one scheduler configuration, with fuzzing on or off.

    Fuzzing draws from the module-level `random()` and cannot be seeded, so a caller that
    needs reproducible dates switches it off instead. Built per call: it is cheap, and a
    shared mutable instance would buy nothing.
    """
    return Scheduler(
        desired_retention=DESIRED_RETENTION,
        learning_steps=(),
        relearning_steps=(),
        enable_fuzzing=fuzzing,
    )


def _card(state: MemoryState | None) -> Card:
    """The library's card for `state`: a blank one for a new word.

    With no learning or relearning steps, every card that has been reviewed once is in the
    review state, which is why the memory state does not store FSRS's state or step.
    """
    if state is None:
        return Card(card_id=_CARD_ID)
    return Card(
        card_id=_CARD_ID,
        state=State.Review,
        step=None,
        stability=state.stability,
        difficulty=state.difficulty,
        due=_as_utc(state.next_review),
        last_review=_as_utc(state.last_review),
    )


def _as_utc(at: datetime) -> datetime:
    """`at` as the same instant in UTC, or a `ValueError` if it cannot be placed in time."""
    if at.utcoffset() is None:
        raise ValueError(
            f"A timezone-aware datetime is needed, got the naive {at.isoformat()}: "
            "without an offset it is no particular instant."
        )
    return at.astimezone(UTC)
