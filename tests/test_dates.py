"""Tests for rendering a calendar date as the Korean phrase a speaker would say.

Written from date-exercise T01's test contract, before the module existed. The contract, in
`oral_korean.korean.dates`:

- `render_date(month: int, day: int, *, year: int | None) -> str` - month and day
  positional, the year keyword-only and required: `None` is an explicit "no year", never a
  default, as `system` has none in `render_number`.
- An impossible date is refused with a `ValueError` (a subclass is fine) before any text is
  produced. Without a year, month and day are checked against a leap year: 29 February is a
  real month and day, 30 February never is.

The phrase is the optional Sino-Korean year + 년, the month name, then the Sino-Korean day +
일, single-spaced: 이천이십육 년 구월 이십일 일. Two month names are irregular, 유월 (June) and
시월 (October); days and years keep the regular 육 and 십.

Every expected string is written out literally from the ticket's tables, never taken from the
code under test. Pure calls: no I/O, no patching.
"""

from __future__ import annotations

import inspect
import re
import sys
from datetime import date, timedelta

import pytest
from conftest import FORBIDDEN_IMPORTS, imported_module_names, signature_shape

from oral_korean.korean import dates
from oral_korean.korean.dates import render_date
from oral_korean.korean.numerals import NumeralSystem, supported_range

# The 15th of every month, no year: one row per month name.
MONTH_CASES: list[tuple[int, str]] = [
    (1, "일월 십오 일"),
    (2, "이월 십오 일"),
    (3, "삼월 십오 일"),
    (4, "사월 십오 일"),
    (5, "오월 십오 일"),
    (6, "유월 십오 일"),  # not 육월
    (7, "칠월 십오 일"),
    (8, "팔월 십오 일"),
    (9, "구월 십오 일"),
    (10, "시월 십오 일"),  # not 십월
    (11, "십일월 십오 일"),  # not 시일월: the irregular 시 is October alone
    (12, "십이월 십오 일"),
]

# Days, no year: the June and October forms belong to the month only.
DAY_CASES: list[tuple[int, int, str]] = [
    (9, 1, "구월 일 일"),
    (9, 2, "구월 이 일"),
    (9, 6, "구월 육 일"),  # 육, not 유
    (9, 10, "구월 십 일"),  # 십, not 시
    (9, 11, "구월 십일 일"),
    (9, 16, "구월 십육 일"),
    (9, 20, "구월 이십 일"),
    (9, 21, "구월 이십일 일"),
    (9, 26, "구월 이십육 일"),
    (9, 30, "구월 삼십 일"),
    (10, 31, "시월 삼십일 일"),
]

# 21 September, with the year.
YEAR_CASES: list[tuple[int, str]] = [
    (2026, "이천이십육 년 구월 이십일 일"),
    (2000, "이천 년 구월 이십일 일"),
    (1999, "천구백구십구 년 구월 이십일 일"),  # 천, not 일천
    (1950, "천구백오십 년 구월 이십일 일"),
    (2006, "이천육 년 구월 이십일 일"),  # 육 in a year, not 유
    (2010, "이천십 년 구월 이십일 일"),  # 십 in a year, not 시
    (2049, "이천사십구 년 구월 이십일 일"),
]

# (year, month, day, expected): the traps combined.
TRAP_CASES: list[tuple[int | None, int, int, str]] = [
    (2026, 6, 6, "이천이십육 년 유월 육 일"),  # two sixes, two readings
    (2010, 10, 10, "이천십 년 시월 십 일"),  # three tens, one irregular
    (2024, 2, 29, "이천이십사 년 이월 이십구 일"),
    (None, 2, 29, "이월 이십구 일"),
    (None, 9, 21, "구월 이십일 일"),
]

# (year, month, day): each refused before any text is produced.
REFUSED_CASES: list[tuple[int | None, int, int]] = [
    (None, 13, 1),
    (None, 0, 1),
    (None, 1, 0),
    (None, 1, 32),
    (None, 2, 30),
    (None, 4, 31),
    (2027, 2, 29),  # 2027 is not a leap year
    (2026, 13, 1),
    (2026, 4, 31),
]

HANGUL_AND_SPACES = re.compile(r"[가-힣]+( [가-힣]+)*")


def _every_day_of(year: int) -> list[date]:
    first = date(year, 1, 1)
    return [
        first + timedelta(days=offset) for offset in range((date(year + 1, 1, 1) - first).days)
    ]


# A leap year, so every month/day pair a yearless phrase may carry is present, 29 February
# included.
EVERY_MONTH_DAY = [(moment.month, moment.day) for moment in _every_day_of(2024)]


# ---------------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------------


def test_render_date_keeps_its_agreed_signature() -> None:
    """Month and day positional, the year keyword-only: `render_date(2026, 9, 21)` is refused."""
    assert signature_shape(render_date) == (["month", "day"], ["year"])


def test_the_year_has_no_default() -> None:
    """Whether the year is spoken is the caller's visible choice, never the renderer's."""
    assert inspect.signature(render_date).parameters["year"].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------------
# The ticket's tables
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("month", "expected"), MONTH_CASES, ids=[str(m) for m, _ in MONTH_CASES])
def test_every_month_name(month: int, expected: str) -> None:
    """Twelve month names, 유월 and 시월 the irregular ones."""
    assert render_date(month, 15, year=None) == expected


@pytest.mark.parametrize(
    ("month", "day", "expected"), DAY_CASES, ids=[f"{m}-{d}" for m, d, _ in DAY_CASES]
)
def test_days_keep_the_regular_sino_reading(month: int, day: int, expected: str) -> None:
    """The day is plain Sino-Korean + 일: 육 and 십 stay, whatever the month does."""
    assert render_date(month, day, year=None) == expected


@pytest.mark.parametrize(("year", "expected"), YEAR_CASES, ids=[str(y) for y, _ in YEAR_CASES])
def test_years_keep_the_regular_sino_reading(year: int, expected: str) -> None:
    """The year is plain Sino-Korean + 년, first in the phrase."""
    assert render_date(9, 21, year=year) == expected


@pytest.mark.parametrize(
    ("year", "month", "day", "expected"),
    TRAP_CASES,
    ids=[f"{y}-{m}-{d}" for y, m, d, _ in TRAP_CASES],
)
def test_the_traps_combined(year: int | None, month: int, day: int, expected: str) -> None:
    """The same digits read two ways in one phrase, and the year present only when asked."""
    assert render_date(month, day, year=year) == expected


def test_no_year_means_no_year_word() -> None:
    """Without the year, 년 appears nowhere."""
    assert "년" not in render_date(9, 21, year=None)


# ---------------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------------


def test_every_month_day_pair_is_hangul_and_single_spaces() -> None:
    """All 366 yearless phrases: Hangul syllables and single spaces only, 월 then a final 일."""
    texts = [render_date(month, day, year=None) for month, day in EVERY_MONTH_DAY]

    malformed = [text for text in texts if HANGUL_AND_SPACES.fullmatch(text) is None]
    without_month = [text for text in texts if "월" not in text]
    without_final_day = [text for text in texts if not text.endswith("일")]

    assert malformed == []
    assert without_month == []
    assert without_final_day == []
    assert len(set(texts)) == len(texts) == 366


def test_every_day_of_a_year_starts_with_that_year() -> None:
    """Every day of 2024 with the year: no ASCII digit, and the year leads the phrase."""
    texts = [
        render_date(moment.month, moment.day, year=moment.year) for moment in _every_day_of(2024)
    ]

    with_digits = [text for text in texts if re.search(r"[0-9]", text)]
    wrong_start = [text for text in texts if not text.startswith("이천이십사 년 ")]

    assert with_digits == []
    assert wrong_start == []


def test_the_irregular_month_names_appear_exactly_for_their_months() -> None:
    """유월 exactly in June, 시월 exactly in October, and never 육월 or 십월."""
    for month, day in EVERY_MONTH_DAY:
        text = render_date(month, day, year=None)
        assert ("유월" in text) == (month == 6), text
        assert ("시월" in text) == (month == 10), text
        assert "육월" not in text, text
        assert "십월" not in text, text


# ---------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "month", "day"), REFUSED_CASES, ids=[f"{y}-{m}-{d}" for y, m, d in REFUSED_CASES]
)
def test_an_impossible_date_is_refused(year: int | None, month: int, day: int) -> None:
    """Refused with a `ValueError`, never clamped or rolled over into the next month."""
    with pytest.raises(ValueError, match=r"."):
        render_date(month, day, year=year)


# ---------------------------------------------------------------------------------
# The number exercise's range is not involved
# ---------------------------------------------------------------------------------


def test_a_year_past_the_number_exercise_range_renders() -> None:
    """2026 is far above `supported_range(SINO).maximum`, which is the numbers draw range.

    Years go through `render_number`, whose own domain reaches 99,999,999; the date path never
    checks a year against the number exercise's range, and that range stays where it is.
    """
    assert supported_range(NumeralSystem.SINO).maximum == 100
    assert render_date(9, 21, year=2026).startswith("이천이십육 년")


# ---------------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------------


def test_dates_imports_only_korean_and_the_standard_library() -> None:
    """Nothing forbidden, nothing from the project outside `korean/`, nothing third-party."""
    imported = imported_module_names(dates)
    project = {name for name in imported if name.split(".")[0] == "oral_korean"}

    assert not [name for name in imported if name.startswith(FORBIDDEN_IMPORTS)]
    assert not [
        name
        for name in project
        if name != "oral_korean" and not name.startswith("oral_korean.korean")
    ]
    assert "oral_korean.korean.numerals" in imported
    assert not [
        name
        for name in imported - project
        if name.split(".")[0] not in sys.stdlib_module_names
    ]
