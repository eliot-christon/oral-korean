"""The clock exercise: draw a time of day to speak, judge the clock position set back.

The same shape as `numbers.py`, functions and frozen value types, no base class. The Korean
comes from `korean/time_of_day.py`; what lives here is the product side: which minutes a
level draws, and how a 12-hour clock position compares with the time that was drawn.

The answer is a structured selection, never text, so there is no "not a number" outcome:
a verdict is correct or incorrect, and a malformed selection is refused before judging.

**The 12-hour mapping is converted here and nowhere else**: 오전 12 is hour 0, 오후 12 is
hour 12, 오후 1 to 11 are 13 to 23. An off-by-twelve would produce a plausible wrong verdict
with no error anywhere, which is why a test sweeps all 1,440 minutes of the day through it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from typing import Final

from oral_korean.korean.time_of_day import HalfPast, OnTheHour, render_time_of_day


class Level(StrEnum):
    """How fine the drawn minutes are, chosen per session."""

    HALF_HOUR = "half_hour"
    FIVE_MINUTES = "five_minutes"
    ANY_MINUTE = "any_minute"


DEFAULT_LEVEL: Final = Level.FIVE_MINUTES
"""The level to practise unless the caller says otherwise."""

_MINUTE_STEPS: Final[dict[Level, int]] = {
    Level.HALF_HOUR: 30,
    Level.FIVE_MINUTES: 5,
    Level.ANY_MINUTE: 1,
}


class InvalidLevelError(ValueError):
    """A level was asked for that this exercise does not have. Refused, never defaulted."""


class Period(StrEnum):
    """오전 or 오후, as the clock's toggle submits it."""

    AM = "am"
    PM = "pm"


@dataclass(frozen=True)
class ClockSelection:
    """A position on a 12-hour clock: what the user submits, and the expected answer.

    Attributes:
        period: morning or afternoon.
        hour: 1 to 12; a 12-hour clock has no 0 and no 13.
        minute: 0 to 59.

    Raises:
        ValueError: the hour or the minute is off the clock face.
    """

    period: Period
    hour: int
    minute: int

    def __post_init__(self) -> None:
        if not 1 <= self.hour <= 12:
            raise ValueError(f"A clock hour is 1 to 12, not {self.hour}.")
        if not 0 <= self.minute <= 59:
            raise ValueError(f"A clock minute is 0 to 59, not {self.minute}.")


@dataclass(frozen=True)
class TimeQuestion:
    """One drawn question: the time, the Korean to speak, and how it was drawn.

    Frozen because it is an answer key, kept pending by the HTTP layer.

    Attributes:
        moment: the time of day to recognise, on a whole minute.
        text: the Korean to be spoken for it.
        level: the level it was drawn at.
        on_the_hour: how minute 0 is read in `text`.
        half_past: how minute 30 is read in `text`.
    """

    moment: time
    text: str
    level: Level
    on_the_hour: OnTheHour
    half_past: HalfPast


class Verdict(StrEnum):
    """How a selection turned out: a clock always holds a time, so only two outcomes."""

    CORRECT = "correct"
    INCORRECT = "incorrect"


@dataclass(frozen=True)
class TimeJudgement:
    """The verdict on one selection, with the expected position and the spoken text."""

    verdict: Verdict
    expected: ClockSelection
    text: str


def minute_step(level: Level) -> int:
    """Return the step between the minutes `level` draws: 30, 5 or 1.

    Raises:
        InvalidLevelError: `level` is not a `Level`.
    """
    return _MINUTE_STEPS[_checked(level)]


def make_time_question(
    moment: time, *, level: Level, on_the_hour: OnTheHour, half_past: HalfPast
) -> TimeQuestion:
    """Build the question for `moment`, spoken under the two readings given.

    The level records how the question was drawn; it does not constrain `moment`.
    """
    return TimeQuestion(
        moment=moment,
        text=render_time_of_day(moment, on_the_hour=on_the_hour, half_past=half_past),
        level=level,
        on_the_hour=on_the_hour,
        half_past=half_past,
    )


def draw_time_question(
    level: Level = DEFAULT_LEVEL, *, rng: random.Random | None = None
) -> TimeQuestion:
    """Draw a time on `level`'s minute grid, over all 24 hours, with random readings.

    Args:
        level: the minute grid to draw on.
        rng: the random source, injected so a test can seed it.

    Raises:
        InvalidLevelError: `level` is not a `Level`, whatever its spelling.
    """
    step = minute_step(level)
    source = random.Random() if rng is None else rng
    hour = source.randrange(24)
    minute = source.randrange(0, 60, step)
    return make_time_question(
        time(hour, minute),
        level=level,
        on_the_hour=source.choice(list(OnTheHour)),
        half_past=source.choice(list(HalfPast)),
    )


def judge_selection(question: TimeQuestion, selection: ClockSelection) -> TimeJudgement:
    """Decide whether `selection` is the time `question` spoke.

    A well-formed minute off the level's grid is a real time that was not asked, so it is
    judged incorrect rather than refused. Never raises.
    """
    expected = _to_selection(question.moment)
    verdict = Verdict.CORRECT if selection == expected else Verdict.INCORRECT
    return TimeJudgement(verdict=verdict, expected=expected, text=question.text)


def _to_selection(moment: time) -> ClockSelection:
    """The 12-hour clock position of `moment`: 00:05 is AM 12:05, 13:00 is PM 1:00."""
    period = Period.AM if moment.hour < 12 else Period.PM
    return ClockSelection(period=period, hour=moment.hour % 12 or 12, minute=moment.minute)


def _checked(level: Level) -> Level:
    if not isinstance(level, Level):
        valid = ", ".join(member.value for member in Level)
        raise InvalidLevelError(f"Unknown level {level!r}: expected one of {valid}.")
    return level
