"""Tests for the clock exercise: drawing a time at a granularity level, judging a clock position.

Framing-mode note: none of the production code below exists yet. These tests are written
from time-exercise T03's acceptance criteria and test contract, and pin this interface of
`oral_korean.exercises.time_of_day`:

- `Level(StrEnum)`: `HALF_HOUR = "half_hour"`, `FIVE_MINUTES = "five_minutes"`,
  `ANY_MINUTE = "any_minute"`, in that order; `DEFAULT_LEVEL` is `Level.FIVE_MINUTES`;
  `minute_step(level) -> int` is 30, 5 and 1.
- `InvalidLevelError(ValueError)`, raised by `draw_time_question` and `minute_step` for
  anything that is not a `Level` member - a raw string included, even a valid value - with a
  message naming every valid level.
- `Period(StrEnum)`: `AM = "am"`, `PM = "pm"`.
- `ClockSelection(period, hour, minute)`, frozen: a 12-hour clock position; `ValueError` for an
  hour outside 1-12 or a minute outside 0-59.
- `TimeQuestion(moment, text, level, on_the_hour, half_past)`, frozen.
- `make_time_question(moment, *, level, on_the_hour, half_past) -> TimeQuestion`.
- `draw_time_question(level=DEFAULT_LEVEL, *, rng=None) -> TimeQuestion`. The hour is
  `rng.randrange(24)`; the stub below relies on that call and on nothing else of the order.
- `Verdict(StrEnum)`: exactly `CORRECT` and `INCORRECT`.
- `TimeJudgement(verdict, expected, text)`, frozen; `expected` is a `ClockSelection`.
- `judge_selection(question, selection) -> TimeJudgement`: the one place the 12-hour
  conversion lives.

Expected Korean text comes from T02's `render_time_of_day` (the test calls the renderer, it
never rebuilds a phrase), except the few phrases the ticket itself writes out, which are
stated literally so a renderer and a judge that agree on a wrong phrase still fail.

Pure: no file, no network, no TTS, no patching.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Callable
from datetime import time
from typing import cast

import pytest
from conftest import FORBIDDEN_IMPORTS, imported_module_names, signature_shape

from oral_korean.exercises import time_of_day as time_exercise
from oral_korean.exercises.time_of_day import (
    DEFAULT_LEVEL,
    ClockSelection,
    InvalidLevelError,
    Level,
    Period,
    TimeJudgement,
    TimeQuestion,
    Verdict,
    draw_time_question,
    judge_selection,
    make_time_question,
    minute_step,
)
from oral_korean.korean.time_of_day import HalfPast, OnTheHour, render_time_of_day

SEED = 20260928
SAMPLE_SIZE = 500
READINGS_SAMPLE_SIZE = 200

LEVELS = list(Level)
LEVEL_IDS = [level.value for level in LEVELS]

DRAWN_1535 = time(15, 35)
TEXT_1535 = "오후 세 시 삼십오 분"
"""Written out by the ticket itself, so stated literally rather than rendered."""


def seeded() -> random.Random:
    """A fresh random source at a fixed seed: a shared one would advance between draws."""
    return random.Random(SEED)


def draws(level: Level, count: int = SAMPLE_SIZE) -> list[TimeQuestion]:
    """`count` questions drawn at `level` from one seeded source."""
    source = seeded()
    return [draw_time_question(level, rng=source) for _ in range(count)]


def question_at(moment: time, level: Level = Level.ANY_MINUTE) -> TimeQuestion:
    """The question for exactly `moment`, read the plain way (bare hour, 반)."""
    return make_time_question(
        moment, level=level, on_the_hour=OnTheHour.BARE, half_past=HalfPast.BAN
    )


def selection(period: Period, hour: int, minute: int) -> ClockSelection:
    return ClockSelection(period=period, hour=hour, minute=minute)


def other_period(period: Period) -> Period:
    return Period.PM if period is Period.AM else Period.AM


class HourForcingRandom(random.Random):
    """A seeded source whose hour draw, `randrange(24)`, returns a chosen hour.

    Everything else (the minute, the two readings) still comes from the seed. `forced`
    records that the hour really came from here, so a draw that found its hour some other
    way fails loudly instead of passing by luck.
    """

    def __init__(self, hour: int) -> None:
        super().__init__(SEED)
        self.hour = hour
        self.forced = False

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        if (stop is None and start == 24) or (start == 0 and stop == 24 and step == 1):
            self.forced = True
            return self.hour
        return super().randrange(start, stop, step)


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        (draw_time_question, ["level"], ["rng"]),
        (make_time_question, ["moment"], ["level", "on_the_hour", "half_past"]),
        (judge_selection, ["question", "selection"], []),
        (minute_step, ["level"], []),
    ],
    ids=["draw_time_question", "make_time_question", "judge_selection", "minute_step"],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """The random source and the two readings are keyword-only: two readings passed
    positionally could be swapped, and nothing at runtime would notice."""
    assert signature_shape(function) == (positional, keyword_only)


def test_levels_are_the_three_of_the_ticket_in_order() -> None:
    """The wire values are the contract with the frontend, and the order is the catalogue's."""
    assert [level.value for level in Level] == ["half_hour", "five_minutes", "any_minute"]


@pytest.mark.parametrize(
    ("level", "step"),
    [(Level.HALF_HOUR, 30), (Level.FIVE_MINUTES, 5), (Level.ANY_MINUTE, 1)],
    ids=LEVEL_IDS,
)
def test_each_level_reports_its_minute_step(level: Level, step: int) -> None:
    """The ticket's table: the step the frontend's clock snaps to."""
    assert minute_step(level) == step


def test_the_default_level_is_five_minutes() -> None:
    assert DEFAULT_LEVEL is Level.FIVE_MINUTES


def test_period_values_are_exact_lowercase() -> None:
    """`am` and `pm` exactly: the HTTP layer does no case folding."""
    assert [period.value for period in Period] == ["am", "pm"]


def test_verdict_has_exactly_two_outcomes() -> None:
    """A clock always shows a time, so there is no `not_a_number`-like third outcome."""
    assert [verdict.name for verdict in Verdict] == ["CORRECT", "INCORRECT"]
    assert [verdict.value for verdict in Verdict] == ["correct", "incorrect"]


def test_invalid_level_error_is_a_value_error() -> None:
    """One family to catch at a boundary, as with the numbers exercise."""
    assert issubclass(InvalidLevelError, ValueError)


# ---------------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------------


def test_a_seeded_five_minute_draw_is_on_the_grid_and_spoken_by_the_renderer() -> None:
    """The text is T02's rendering of the drawn time under the drawn readings."""
    question = draw_time_question(Level.FIVE_MINUTES, rng=seeded())

    assert question.moment.minute % 5 == 0
    assert question.level is Level.FIVE_MINUTES
    assert question.text == render_time_of_day(
        question.moment, on_the_hour=question.on_the_hour, half_past=question.half_past
    )


@pytest.mark.parametrize("level", LEVELS, ids=LEVEL_IDS)
def test_the_same_seed_draws_the_same_question(level: Level) -> None:
    """Time, readings and text all come from the injected source and nothing else."""
    first = draw_time_question(level, rng=seeded())
    second = draw_time_question(level, rng=seeded())

    assert first == second


@pytest.mark.parametrize("level", LEVELS, ids=LEVEL_IDS)
def test_every_draw_is_rendered_by_t02_under_its_own_readings(level: Level) -> None:
    """Over many draws, not one: a reading stored on the question but not used for the text
    (or the reverse) only shows on the draws where the two readings matter."""
    for question in draws(level):
        assert question.level is level
        assert isinstance(question.on_the_hour, OnTheHour)
        assert isinstance(question.half_past, HalfPast)
        assert question.text == render_time_of_day(
            question.moment, on_the_hour=question.on_the_hour, half_past=question.half_past
        )


@pytest.mark.parametrize(
    ("level", "grid"),
    [
        (Level.HALF_HOUR, {0, 30}),
        (Level.FIVE_MINUTES, set(range(0, 60, 5))),
    ],
    ids=["half_hour", "five_minutes"],
)
def test_draws_stay_on_the_levels_grid_and_cover_it(level: Level, grid: set[int]) -> None:
    """Every minute on the grid, and the whole grid reached: 500 draws over at most 12
    values miss one with a probability far below anything a seed would ever hit."""
    minutes = {question.moment.minute for question in draws(level)}

    assert minutes == grid


def test_any_minute_draws_stay_in_the_hour_and_leave_the_five_minute_grid() -> None:
    """The level is honoured, not collapsed to the default five-minute grid."""
    minutes = [question.moment.minute for question in draws(Level.ANY_MINUTE)]

    assert all(0 <= minute <= 59 for minute in minutes)
    assert any(minute % 5 != 0 for minute in minutes)


@pytest.mark.parametrize("level", LEVELS, ids=LEVEL_IDS)
def test_draws_cover_all_twenty_four_hours(level: Level) -> None:
    """Midnight and noon included: the hour is drawn over the whole day, not 1-12."""
    hours = {question.moment.hour for question in draws(level)}

    assert hours == set(range(24))


@pytest.mark.parametrize("level", LEVELS, ids=LEVEL_IDS)
def test_draws_are_whole_naive_minutes(level: Level) -> None:
    """No seconds and no zone: the renderer refuses both, and the clock shows neither."""
    for question in draws(level, count=50):
        assert question.moment.second == 0
        assert question.moment.microsecond == 0
        assert question.moment.tzinfo is None


@pytest.mark.parametrize("level", LEVELS, ids=LEVEL_IDS)
def test_draws_speak_both_morning_and_afternoon(level: Level) -> None:
    texts = [question.text for question in draws(level)]

    assert any(text.startswith("오전 ") for text in texts)
    assert any(text.startswith("오후 ") for text in texts)


@pytest.mark.parametrize(
    ("hour", "prefix"),
    [(0, "오전 열두 시"), (12, "오후 열두 시")],
    ids=["midnight", "noon"],
)
def test_midnight_and_noon_are_reachable_and_spoken_as_twelve(hour: int, prefix: str) -> None:
    """Both ends of the 12-hour reading, forced rather than left to chance."""
    source = HourForcingRandom(hour)

    question = draw_time_question(Level.FIVE_MINUTES, rng=source)

    assert source.forced, "the hour was not drawn with randrange(24)"
    assert question.moment.hour == hour
    assert question.text.startswith(prefix)


def test_both_readings_of_the_half_hour_and_of_the_hour_occur() -> None:
    """The :00 and :30 readings are drawn per question, so a session hears all four."""
    texts = [question.text for question in draws(Level.HALF_HOUR, READINGS_SAMPLE_SIZE)]

    assert any(text.endswith(" 반") for text in texts)
    assert any(text.endswith(" 삼십 분") for text in texts)
    assert any(text.endswith(" 시") for text in texts)
    assert any(text.endswith(" 정각") for text in texts)


def test_no_level_draws_at_the_default_five_minute_grid() -> None:
    """Leaving the level out is exactly asking for `five_minutes`, not some other grid."""
    implicit = draw_time_question(rng=seeded())
    explicit = draw_time_question(Level.FIVE_MINUTES, rng=seeded())

    assert implicit == explicit
    assert implicit.level is Level.FIVE_MINUTES


def test_omitting_rng_falls_back_to_a_real_random_source() -> None:
    """The one call leaving `rng` out, so the fallback source runs at least once."""
    question = draw_time_question(Level.HALF_HOUR)

    assert question.moment.minute in {0, 30}
    assert question.text == render_time_of_day(
        question.moment, on_the_hour=question.on_the_hour, half_past=question.half_past
    )


@pytest.mark.parametrize(
    "level",
    ["quarter_hour", "", "FIVE_MINUTES", "five_minutes", " five_minutes", None, 5],
    ids=["unknown", "empty", "upper-case", "raw-string", "padded", "none", "a-number"],
)
def test_an_unknown_level_is_rejected_naming_every_valid_level(level: object) -> None:
    """Never replaced by the default. Even the raw string "five_minutes" is refused: the
    module takes `Level` members, and the HTTP layer is where strings become levels."""
    with pytest.raises(InvalidLevelError) as excinfo:
        draw_time_question(cast(Level, level), rng=seeded())

    message = str(excinfo.value)
    for valid in Level:
        assert valid.value in message


@pytest.mark.parametrize("level", ["quarter_hour", "five_minutes", None], ids=str)
def test_minute_step_rejects_an_unknown_level_too(level: object) -> None:
    with pytest.raises(InvalidLevelError):
        minute_step(cast(Level, level))


@pytest.mark.parametrize(
    "field_name", ["moment", "text", "level", "on_the_hour", "half_past"]
)
def test_a_drawn_question_cannot_be_mutated(field_name: str) -> None:
    """Pending questions sit in memory; a mutable one is a rewritable answer key."""
    question = draw_time_question(Level.FIVE_MINUTES, rng=seeded())

    assert [field.name for field in dataclasses.fields(question)] == [
        "moment",
        "text",
        "level",
        "on_the_hour",
        "half_past",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(question, field_name, "tampered")


@pytest.mark.parametrize("level", LEVELS, ids=LEVEL_IDS)
def test_no_drawn_text_contains_an_ascii_digit(level: Level) -> None:
    """Digits handed to the engine get read by its own normaliser, in the wrong system."""
    for question in draws(level):
        assert not any(character in "0123456789" for character in question.text), question.text


# ---------------------------------------------------------------------------------
# Building a question for a given time
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("half_past", "expected"),
    [(HalfPast.BAN, "오후 네 시 반"), (HalfPast.MINUTES, "오후 네 시 삼십 분")],
    ids=["ban", "minutes"],
)
def test_make_time_question_speaks_the_reading_it_is_given(
    half_past: HalfPast, expected: str
) -> None:
    question = make_time_question(
        time(16, 30), level=Level.HALF_HOUR, on_the_hour=OnTheHour.BARE, half_past=half_past
    )

    assert question.text == expected
    assert question.moment == time(16, 30)
    assert question.level is Level.HALF_HOUR
    assert question.half_past is half_past


def test_make_time_question_gives_the_text_the_ticket_names_for_15_35() -> None:
    assert question_at(DRAWN_1535, Level.FIVE_MINUTES).text == TEXT_1535


# ---------------------------------------------------------------------------------
# Judging, drawn time 15:35
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chosen", "verdict"),
    [
        (selection(Period.PM, 3, 35), Verdict.CORRECT),
        (selection(Period.AM, 3, 35), Verdict.INCORRECT),
        (selection(Period.PM, 4, 35), Verdict.INCORRECT),
        (selection(Period.PM, 3, 30), Verdict.INCORRECT),
        (selection(Period.PM, 3, 7), Verdict.INCORRECT),
        (selection(Period.AM, 3, 30), Verdict.INCORRECT),
    ],
    ids=["right", "wrong-period", "wrong-hour", "wrong-minute", "off-the-grid", "two-wrong"],
)
def test_judging_a_selection_against_15_35(chosen: ClockSelection, verdict: Verdict) -> None:
    """Right only when all three agree. 3:07 is off the five-minute grid but a real time:
    judged incorrect, never rejected. Both verdicts carry the expected position and the
    spoken text, so the feedback never depends on how the answer was wrong."""
    result = judge_selection(question_at(DRAWN_1535, Level.FIVE_MINUTES), chosen)

    assert result.verdict is verdict
    assert result.expected == selection(Period.PM, 3, 35)
    assert result.text == TEXT_1535


def test_judging_the_same_selection_twice_gives_the_same_result() -> None:
    """No hidden state: no attempt counter, no consumed question."""
    question = question_at(DRAWN_1535, Level.FIVE_MINUTES)
    wrong = selection(Period.AM, 3, 35)

    first = judge_selection(question, wrong)
    second = judge_selection(question, wrong)

    assert first == second
    assert question == question_at(DRAWN_1535, Level.FIVE_MINUTES)


@pytest.mark.parametrize("field_name", ["verdict", "expected", "text"])
def test_a_judgement_cannot_be_mutated(field_name: str) -> None:
    result: TimeJudgement = judge_selection(
        question_at(DRAWN_1535, Level.FIVE_MINUTES), selection(Period.AM, 3, 35)
    )

    assert [field.name for field in dataclasses.fields(result)] == ["verdict", "expected", "text"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(result, field_name, "tampered")


# ---------------------------------------------------------------------------------
# The clock selection itself
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(1, 0), (12, 0), (1, 59), (12, 59)],
    ids=["hour-1", "hour-12", "minute-59", "both-top"],
)
def test_a_selection_accepts_the_ends_of_the_clock(hour: int, minute: int) -> None:
    chosen = selection(Period.AM, hour, minute)

    assert (chosen.period, chosen.hour, chosen.minute) == (Period.AM, hour, minute)


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(0, 0), (13, 0), (-1, 0), (1, 60), (1, -1)],
    ids=["hour-0", "hour-13", "hour-negative", "minute-60", "minute-negative"],
)
def test_a_selection_off_the_clock_face_is_refused(hour: int, minute: int) -> None:
    """A 12-hour clock has no 0 and no 13: rejected, never wrapped round."""
    with pytest.raises(ValueError):
        selection(Period.PM, hour, minute)


@pytest.mark.parametrize("field_name", ["period", "hour", "minute"])
def test_a_selection_cannot_be_mutated(field_name: str) -> None:
    chosen = selection(Period.PM, 3, 35)

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(chosen, field_name, 4)


# ---------------------------------------------------------------------------------
# The 12-hour mapping
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("drawn", "right", "wrong"),
    [
        (time(0, 5), selection(Period.AM, 12, 5), selection(Period.PM, 12, 5)),
        (time(12, 0), selection(Period.PM, 12, 0), selection(Period.AM, 12, 0)),
        (time(13, 0), selection(Period.PM, 1, 0), selection(Period.AM, 1, 0)),
        (time(11, 59), selection(Period.AM, 11, 59), selection(Period.PM, 11, 59)),
        (time(23, 59), selection(Period.PM, 11, 59), selection(Period.AM, 11, 59)),
        (time(1, 0), selection(Period.AM, 1, 0), selection(Period.PM, 1, 0)),
    ],
    ids=["00:05", "12:00", "13:00", "11:59", "23:59", "01:00"],
)
def test_the_twelve_hour_mapping_at_its_edges(
    drawn: time, right: ClockSelection, wrong: ClockSelection
) -> None:
    """오전 12 is hour 0 and 오후 12 is hour 12: the expected position is reported the way
    the clock shows it, never as `am, 0, 5`."""
    question = question_at(drawn)

    correct = judge_selection(question, right)
    incorrect = judge_selection(question, wrong)

    assert correct.verdict is Verdict.CORRECT
    assert incorrect.verdict is Verdict.INCORRECT
    assert correct.expected == right
    assert incorrect.expected == right


def test_every_minute_of_the_day_round_trips_through_the_clock() -> None:
    """All 1,440 minutes: the reported position is judged correct, the same position with
    the other period incorrect, the position agrees with the period word spoken, and no two
    times of day share a position. An off-by-twelve anywhere in the day breaks one of these.
    """
    positions: set[ClockSelection] = set()
    for hour in range(24):
        for minute in range(60):
            question = question_at(time(hour, minute))
            expected = judge_selection(question, selection(Period.AM, 12, 0)).expected

            assert judge_selection(question, expected).verdict is Verdict.CORRECT
            flipped = selection(other_period(expected.period), expected.hour, expected.minute)
            assert judge_selection(question, flipped).verdict is Verdict.INCORRECT

            assert 1 <= expected.hour <= 12
            assert expected.hour % 12 == hour % 12
            assert expected.minute == minute
            assert expected.period is (Period.AM if hour < 12 else Period.PM)
            spoken_period = "오전" if expected.period is Period.AM else "오후"
            assert question.text.startswith(spoken_period + " ")
            positions.add(expected)

    assert len(positions) == 24 * 60


# ---------------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------------


def test_the_exercise_module_imports_only_korean_from_the_project() -> None:
    """The layering rule, checked here too because this module is what it is about: the
    exercise decides what to say and whether a position is right, and nothing else."""
    names = imported_module_names(time_exercise)

    forbidden = {
        name for name in names for prefix in FORBIDDEN_IMPORTS if name.startswith(prefix)
    }
    project = {
        name for name in names if name == "oral_korean" or name.startswith("oral_korean.")
    }
    outside_korean = {name for name in project if not name.startswith("oral_korean.korean")}

    assert not forbidden
    assert not outside_korean
