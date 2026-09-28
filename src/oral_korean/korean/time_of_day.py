"""A time of day as a Korean speaker says it: 오후 세 시 삼십오 분.

One phrase, both numeral systems: the hour is **native** Korean in its attributive form
(세 시, never 셋 시 or 삼 시), the minutes are **Sino**-Korean (삼십오 분). This is exactly
what a generic digit normaliser gets wrong, which is why the text is written out here in
Hangul rather than handed to the speech engine as "3시 35분".

Conventions, all pinned by `tests/test_time_of_day.py`:

- the period is always spoken, on a 12-hour reading as phone clocks show it: 00:xx is
  오전 열두 시, 12:xx is 오후 열두 시;
- minute 0 has no minute word (세 시, never 세 시 영 분), or is 정각 if the caller asks;
- minute 30 is 반 or 삼십 분, as the caller asks;
- words are separated by single spaces, unit words spaced from their numerals.

Language, not exercise logic: how 15:35 is said does not depend on how an exercise draws or
judges it. The module is pure and imports only `korean/` and the standard library.
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum
from typing import Final

from oral_korean.korean.numerals import NumeralSystem, render_native_attributive, render_number


class OnTheHour(StrEnum):
    """How minute 0 is read: bare (세 시) or with 정각 (세 시 정각)."""

    BARE = "bare"
    JEONGGAK = "jeonggak"


class HalfPast(StrEnum):
    """How minute 30 is read: 반 (세 시 반) or in minutes (세 시 삼십 분)."""

    BAN = "ban"
    MINUTES = "minutes"


_MORNING: Final = "오전"
_AFTERNOON: Final = "오후"
_HOUR: Final = "시"
_MINUTE: Final = "분"
_ON_THE_HOUR: Final = "정각"
_HALF_PAST: Final = "반"


def render_time_of_day(moment: time, *, on_the_hour: OnTheHour, half_past: HalfPast) -> str:
    """Return `moment` as the Korean phrase a speaker would say, in Hangul only.

    Args:
        moment: a naive time on a whole minute.
        on_the_hour: how minute 0 is read. No default: the choice is always explicit.
        half_past: how minute 30 is read. No default either.

    Raises:
        ValueError: `moment` carries seconds, microseconds or a time zone, or a reading is
            unknown. Never truncated: the phrase has no seconds and no zone, and dropping
            them silently would speak a different time from the one asked.
    """
    if moment.second or moment.microsecond:
        raise ValueError(f"Cannot speak {moment.isoformat()}: the phrase has no seconds.")
    if moment.tzinfo is not None:
        raise ValueError(f"Cannot speak {moment.isoformat()}: the phrase has no time zone.")
    if not isinstance(on_the_hour, OnTheHour):
        raise ValueError(f"Unknown reading of the hour {on_the_hour!r}.")
    if not isinstance(half_past, HalfPast):
        raise ValueError(f"Unknown reading of the half hour {half_past!r}.")

    period = _MORNING if moment.hour < 12 else _AFTERNOON
    # 0 and 12 both read as 열두 시; 13 is 오후 한 시, never 열세 시.
    clock_hour = moment.hour % 12 or 12
    words = [period, render_native_attributive(clock_hour), _HOUR]
    words.extend(_minute_words(moment.minute, on_the_hour, half_past))
    return " ".join(words)


def _minute_words(minute: int, on_the_hour: OnTheHour, half_past: HalfPast) -> list[str]:
    """The words after 시 for `minute`, under the two readings."""
    if minute == 0:
        return [_ON_THE_HOUR] if on_the_hour is OnTheHour.JEONGGAK else []
    if minute == 30 and half_past is HalfPast.BAN:
        return [_HALF_PAST]
    return [render_number(minute, NumeralSystem.SINO), _MINUTE]
