"""A calendar date as a Korean speaker says it: 이천이십육 년 구월 이십일 일.

Sino-Korean throughout - the optional year + 년, the month name, the day + 일 - with one
irregularity: two month names are not the plain Sino reading. June is 유월 (not 육월) and
October is 시월 (not 십월). Only the month names change; days and years keep 육 and 십, so
6 June 2026 is 이천이십육 년 유월 육 일 - the same digit read two ways in one phrase. This is
why the text is written out here in Hangul rather than handed to the speech engine as
"6월 6일".

Conventions, all pinned by `tests/test_dates.py`:

- the year is spoken only when the caller passes one, a choice made visibly (`year=None`);
- words are separated by single spaces, 년 and 일 spaced from their numerals, the month name
  written as one word (유월 and 시월 are lexicalised, so every month is written alike).

Years go through `render_number` directly, whose domain covers them; they are never checked
against `supported_range(NumeralSystem.SINO)`, which is the number exercise's draw range.
The module is pure and imports only `korean/` and the standard library.
"""

from __future__ import annotations

from datetime import date
from typing import Final

from oral_korean.korean.numerals import NumeralSystem, render_number

# The two month names that are not the plain Sino-Korean number + 월.
_IRREGULAR_MONTHS: Final = {6: "유월", 10: "시월"}
_MONTH: Final = "월"
_YEAR: Final = "년"
_DAY: Final = "일"
# Any leap year: a yearless month and day is real if it exists in some year, so 29 February
# is accepted and 30 February never is.
_LEAP_YEAR: Final = 2024


def render_date(month: int, day: int, *, year: int | None) -> str:
    """Return the date as the Korean phrase a speaker would say, in Hangul only.

    Args:
        month: 1 to 12.
        day: 1 to the month's length.
        year: the year to speak first, or `None` to leave it out. No default: whether the
            year is spoken is always the caller's explicit choice.

    Raises:
        ValueError: the month and day (and year, when given) are not a real calendar date.
            Never clamped or rolled over: speaking a different date from the one asked would
            teach the wrong answer.
    """
    date(_LEAP_YEAR if year is None else year, month, day)

    month_name = _IRREGULAR_MONTHS.get(month, render_number(month, NumeralSystem.SINO) + _MONTH)
    words = [month_name, render_number(day, NumeralSystem.SINO), _DAY]
    if year is not None:
        words[:0] = [render_number(year, NumeralSystem.SINO), _YEAR]
    return " ".join(words)
