"""Tests for the calendar exercise's pure logic: drawing a date and judging a picked day.

The contract (date-exercise T02), in `oral_korean.exercises.dates`:

- `draw_date_question(*, rng)` decides from `rng.random()` whether the year is spoken
  (below `YEAR_SPOKEN_PROBABILITY`), then draws the day with one `rng.randrange`: over every
  day of `YEAR_WINDOW` with the year, over the 365 days of a common year without it.
- `judge_selection(question, selection)` compares the year only when the question asks for
  it, and refuses (`SelectionError`, a `ValueError`) a selection whose year is present or
  absent against the question. `DateSelection` itself refuses a day that is not real.

The Korean is always taken from `render_date` (pinned by `test_dates.py`), never rebuilt here.
Pure calls, no patching.
"""

from __future__ import annotations

import dataclasses
import random
import re
from datetime import date

import pytest
from conftest import FORBIDDEN_IMPORTS, imported_module_names, signature_shape

from oral_korean.exercises import dates
from oral_korean.exercises.dates import (
    YEAR_SPOKEN_PROBABILITY,
    YEAR_WINDOW,
    DateQuestion,
    DateSelection,
    SelectionError,
    Verdict,
    draw_date_question,
    judge_selection,
    make_date_question,
)
from oral_korean.korean.dates import render_date


class StubRandom(random.Random):
    """A random source whose two draws are fixed: `random()` and the one `randrange`."""

    def __init__(self, *, speaks_year: bool, index: int | str) -> None:
        super().__init__(0)
        self._roll = 0.0 if speaks_year else 0.999
        self._index = index

    def random(self) -> float:
        return self._roll

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        del step
        span = start if stop is None else stop - start
        return span - 1 if self._index == "last" else int(self._index)


DATED: DateQuestion = make_date_question(DateSelection(2026, 9, 21))
YEARLESS: DateQuestion = make_date_question(DateSelection(None, 6, 6))


# ---------------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------------


def test_a_question_that_speaks_the_year_asks_for_it() -> None:
    question = draw_date_question(rng=StubRandom(speaks_year=True, index=100))
    expected = question.expected

    assert question.asks_year
    assert expected.year is not None
    assert question.text == render_date(expected.month, expected.day, year=expected.year)


def test_a_question_that_does_not_speak_the_year_does_not_ask_for_it() -> None:
    question = draw_date_question(rng=StubRandom(speaks_year=False, index=100))
    expected = question.expected

    assert not question.asks_year
    assert expected.year is None
    assert question.text == render_date(expected.month, expected.day, year=None)
    assert "년" not in question.text


def test_the_same_seed_draws_the_same_question() -> None:
    assert draw_date_question(rng=random.Random(7)) == draw_date_question(rng=random.Random(7))


def test_the_year_is_spoken_about_one_question_in_two() -> None:
    assert YEAR_SPOKEN_PROBABILITY == 0.5


def test_many_draws_stay_in_the_window_and_never_draw_a_yearless_leap_day() -> None:
    """2,000 seeded draws: both kinds occur, every year is in the window, no yearless 29/2."""
    source = random.Random(2026)
    questions = [draw_date_question(rng=source) for _ in range(2000)]
    years = [q.expected.year for q in questions if q.expected.year is not None]
    yearless = [q.expected for q in questions if q.expected.year is None]

    assert years and yearless
    assert all(YEAR_WINDOW.minimum <= year <= YEAR_WINDOW.maximum for year in years)
    assert not [e for e in yearless if (e.month, e.day) == (2, 29)]


def test_the_window_bounds_are_reachable() -> None:
    """The first and last day of the window, read from the constant, not from literals."""
    first = draw_date_question(rng=StubRandom(speaks_year=True, index=0)).expected
    last = draw_date_question(rng=StubRandom(speaks_year=True, index="last")).expected

    assert first == DateSelection(YEAR_WINDOW.minimum, 1, 1)
    assert last == DateSelection(YEAR_WINDOW.maximum, 12, 31)


def test_the_yearless_bounds_are_new_year_and_new_year_eve() -> None:
    first = draw_date_question(rng=StubRandom(speaks_year=False, index=0)).expected
    last = draw_date_question(rng=StubRandom(speaks_year=False, index="last")).expected

    assert first == DateSelection(None, 1, 1)
    assert last == DateSelection(None, 12, 31)


@pytest.mark.parametrize("field_name", ["expected", "text"])
def test_a_drawn_question_is_frozen(field_name: str) -> None:
    question = draw_date_question(rng=random.Random(1))

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(question, field_name, "tampered")


def test_no_drawn_text_contains_a_digit() -> None:
    source = random.Random(99)
    texts = [draw_date_question(rng=source).text for _ in range(500)]

    assert not [text for text in texts if re.search(r"[0-9]", text)]


# ---------------------------------------------------------------------------------
# Judging a dated question: 2026-09-21
# ---------------------------------------------------------------------------------


def test_the_dated_question_speaks_its_year() -> None:
    assert DATED.text == "이천이십육 년 구월 이십일 일"


def test_the_right_dated_answer_is_correct() -> None:
    assert judge_selection(DATED, DateSelection(2026, 9, 21)).verdict is Verdict.CORRECT


@pytest.mark.parametrize(
    ("year", "month", "day"),
    [(2025, 9, 21), (2026, 8, 21), (2026, 9, 22), (1900, 9, 21)],
    ids=["year-wrong", "month-wrong", "day-wrong", "outside-the-window"],
)
def test_a_wrong_dated_answer_is_incorrect(year: int, month: int, day: int) -> None:
    """A real date that is wrong, even outside the window, is judged, not refused."""
    judgement = judge_selection(DATED, DateSelection(year, month, day))

    assert judgement.verdict is Verdict.INCORRECT
    assert judgement.expected == DateSelection(2026, 9, 21)
    assert judgement.text == DATED.text


# ---------------------------------------------------------------------------------
# Judging a yearless question: 6 June
# ---------------------------------------------------------------------------------


def test_the_right_yearless_answer_is_correct() -> None:
    assert judge_selection(YEARLESS, DateSelection(None, 6, 6)).verdict is Verdict.CORRECT


@pytest.mark.parametrize(
    ("month", "day"),
    [(6, 16), (10, 6), (2, 29)],
    ids=["day-wrong", "october-for-june", "yearless-leap-day"],
)
def test_a_wrong_yearless_answer_is_incorrect(month: int, day: int) -> None:
    """유월 heard as 시월 is exactly the mistake the exercise catches; a yearless 29 February
    is a real month and day, judged rather than refused."""
    judgement = judge_selection(YEARLESS, DateSelection(None, month, day))

    assert judgement.verdict is Verdict.INCORRECT
    assert judgement.expected == DateSelection(None, 6, 6)
    assert judgement.text == "유월 육 일"


# ---------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------


def test_a_year_on_a_yearless_question_is_refused() -> None:
    with pytest.raises(SelectionError, match="does not ask for the year"):
        judge_selection(YEARLESS, DateSelection(2026, 6, 6))


def test_a_missing_year_on_a_dated_question_is_refused() -> None:
    with pytest.raises(SelectionError, match="asks for the year"):
        judge_selection(DATED, DateSelection(None, 9, 21))


@pytest.mark.parametrize(
    ("year", "month", "day"),
    [(None, 2, 30), (2026, 4, 31), (2027, 2, 29), (None, 13, 1), (None, 1, 0)],
    ids=["yearless-30-feb", "31-april", "29-feb-2027", "month-13", "day-0"],
)
def test_a_selection_that_is_not_a_date_is_refused(year: int | None, month: int, day: int) -> None:
    with pytest.raises(SelectionError):
        DateSelection(year, month, day)


def test_a_selection_error_is_a_value_error() -> None:
    assert issubclass(SelectionError, ValueError)


def test_judging_is_repeatable() -> None:
    selection = DateSelection(2026, 9, 22)

    assert judge_selection(DATED, selection) == judge_selection(DATED, selection)


def test_a_drawn_question_answered_with_itself_is_correct() -> None:
    """Round trip over many draws: the expected selection always judges correct."""
    source = random.Random(5)
    for _ in range(300):
        question = draw_date_question(rng=source)
        assert judge_selection(question, question.expected).verdict is Verdict.CORRECT
        expected = question.expected
        if expected.year is not None:
            assert date(expected.year, expected.month, expected.day)


# ---------------------------------------------------------------------------------
# Purity and signatures
# ---------------------------------------------------------------------------------


def test_the_exercise_imports_only_korean_and_nothing_forbidden() -> None:
    imported = imported_module_names(dates)
    project = [name for name in imported if name.startswith("oral_korean.")]

    assert not [name for name in imported if name.startswith(FORBIDDEN_IMPORTS)]
    assert not [name for name in project if not name.startswith("oral_korean.korean")]


def test_draw_and_judge_keep_their_signatures() -> None:
    assert signature_shape(draw_date_question) == ([], ["rng"])
    assert signature_shape(judge_selection) == (["question", "selection"], [])
