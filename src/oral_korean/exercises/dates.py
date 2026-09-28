"""The calendar exercise: draw a date to speak, judge the day picked back.

The same shape as `time_of_day.py`, functions and frozen value types, no base class. The
Korean comes from `korean/dates.py`; what lives here is the product side: the year window,
how often the year is spoken, and how a picked day compares with the date that was drawn.

A question either asks for the year or does not, and the client is told which (the shape
of the answer, not its value). **Whether the year is compared is decided here and nowhere
else**: a selection must carry a year exactly when the question asks for one, and one that
does not is refused rather than judged with the year ignored or defaulted. A selection
that is not a real date is refused too. A real date that is wrong - outside the window
included - is judged incorrect.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Final

from oral_korean.korean.dates import render_date


@dataclass(frozen=True)
class YearRange:
    """The years a dated question is drawn from, both ends included."""

    minimum: int
    maximum: int


YEAR_WINDOW: Final = YearRange(minimum=1950, maximum=2049)
"""A product choice, not a language fact: birthdays, history within living memory and
near-future appointments. `render_number` speaks far wider years."""

YEAR_SPOKEN_PROBABILITY: Final = 0.5
"""How often a question speaks, and asks for, the year."""

# Any leap year: a yearless month and day is real if it exists in some year.
_LEAP_YEAR: Final = 2024
# Any common year: a yearless question is drawn from its 365 days, so never 29 February -
# the calendar shows a real year's grid, which lacks the 29th three years in four.
_COMMON_YEAR: Final = 2025


class SelectionError(ValueError):
    """A selection that cannot be judged: not a real date, or the wrong shape for the question.

    Its message names what is wrong with the selection and nothing of the expected answer.
    """


@dataclass(frozen=True)
class DateSelection:
    """A picked day: what the user submits, and the expected answer.

    Attributes:
        year: the year, or `None` when the question does not ask for it.
        month: 1 to 12.
        day: 1 to 31, and a real day of that month.

    Raises:
        SelectionError: not a real date; without a year, not a real month and day (29
            February is one, 30 February is not).
    """

    year: int | None
    month: int
    day: int

    def __post_init__(self) -> None:
        try:
            date(_LEAP_YEAR if self.year is None else self.year, self.month, self.day)
        except ValueError as exc:
            raise SelectionError(f"Not a real date: {exc}.") from exc


@dataclass(frozen=True)
class DateQuestion:
    """One drawn question: the date to recognise and the Korean to speak for it.

    Frozen because it is an answer key, kept pending by the HTTP layer.

    Attributes:
        expected: the date, its year `None` when the year is not spoken.
        text: the Korean to be spoken for it.
    """

    expected: DateSelection
    text: str

    @property
    def asks_year(self) -> bool:
        """Whether the year is spoken, and so must be picked."""
        return self.expected.year is not None


class Verdict(StrEnum):
    """How a selection turned out: a calendar always holds a day, so only two outcomes."""

    CORRECT = "correct"
    INCORRECT = "incorrect"


@dataclass(frozen=True)
class DateJudgement:
    """The verdict on one selection, with the expected date and the spoken text."""

    verdict: Verdict
    expected: DateSelection
    text: str


def make_date_question(expected: DateSelection) -> DateQuestion:
    """Build the question for `expected`, speaking the year exactly when it has one."""
    return DateQuestion(
        expected=expected,
        text=render_date(expected.month, expected.day, year=expected.year),
    )


def draw_date_question(*, rng: random.Random | None = None) -> DateQuestion:
    """Draw a date, deciding at random whether its year is spoken.

    With the year, the day is uniform over every day of `YEAR_WINDOW`; without it, uniform
    over the 365 days of a common year, so 29 February is never drawn yearless.

    Args:
        rng: the random source, injected so a test can seed it.
    """
    source = random.Random() if rng is None else rng
    if source.random() < YEAR_SPOKEN_PROBABILITY:
        first = date(YEAR_WINDOW.minimum, 1, 1)
        span = (date(YEAR_WINDOW.maximum + 1, 1, 1) - first).days
        drawn = first + timedelta(days=source.randrange(span))
        return make_date_question(DateSelection(drawn.year, drawn.month, drawn.day))
    drawn = date(_COMMON_YEAR, 1, 1) + timedelta(days=source.randrange(365))
    return make_date_question(DateSelection(None, drawn.month, drawn.day))


def judge_selection(question: DateQuestion, selection: DateSelection) -> DateJudgement:
    """Decide whether `selection` is the date `question` spoke.

    The year is compared only when the question asks for it, and then it must be given.

    Raises:
        SelectionError: the selection carries a year the question does not ask for, or
            lacks one it does. Refused, never judged with the year ignored or defaulted.
    """
    if question.asks_year and selection.year is None:
        raise SelectionError("This question asks for the year.")
    if not question.asks_year and selection.year is not None:
        raise SelectionError("This question does not ask for the year.")
    verdict = Verdict.CORRECT if selection == question.expected else Verdict.INCORRECT
    return DateJudgement(verdict=verdict, expected=question.expected, text=question.text)
