"""Tests for rendering a time of day as the Korean phrase a speaker would say.

Framing-mode note: none of the production code below exists yet. These tests are written
from time-exercise T02's acceptance criteria and test contract, and they define the contract
the implementation must satisfy, in the new module `oral_korean.korean.time_of_day`:

- `render_time_of_day(moment: datetime.time, *, on_the_hour: OnTheHour, half_past: HalfPast)
  -> str` - `moment` positional, both readings keyword-only and required. No defaults, for the
  same reason `render_number` has none for `system`: which reading a question uses is a choice
  the caller makes visibly, not one the renderer makes silently.
- `OnTheHour` - a `StrEnum` with exactly `BARE = "bare"` (세 시) and `JEONGGAK = "jeonggak"`
  (세 시 정각). It changes minute 0 and nothing else.
- `HalfPast` - a `StrEnum` with exactly `BAN = "ban"` (세 시 반) and `MINUTES = "minutes"`
  (세 시 삼십 분). It changes minute 30 and nothing else.
- A `moment` carrying non-zero seconds or microseconds is refused with a `ValueError` (a
  subclass is fine): the phrase has no seconds, and dropping them would be a silent clamp.
  Hour 24 and minute 60 are refused by `datetime.time` itself; the tests assert the refusal
  whatever layer raises it.

The phrase is 오전/오후, the hour in native Korean's attributive form + 시, then the minutes in
Sino-Korean + 분, single-spaced: 오후 세 시 삼십오 분. Twelve-hour, phone-clock reading: 00:xx is
오전 열두 시, 12:xx is 오후 열두 시. Minute 0 has no minute word.

Every expected string below is written out literally from the ticket's tables, never taken
from the code under test. The one oracle borrowed from elsewhere is `render_number` for the
minutes in the whole-day sweep, which the ticket names as the minutes' source and
`test_numerals.py` pins on its own.

Everything here is a pure function call: no file I/O, no network, no TTS, no patching.
"""

from __future__ import annotations

import inspect
import sys
from datetime import UTC, time
from functools import cache
from typing import cast

import pytest
from conftest import FORBIDDEN_IMPORTS, imported_module_names, signature_shape

from oral_korean.korean import time_of_day
from oral_korean.korean.numerals import NumeralSystem, render_number
from oral_korean.korean.time_of_day import HalfPast, OnTheHour, render_time_of_day

# The ticket's hour table, whole: every hour at minute 0, bare reading. Noon and midnight are
# the two traps (both 열두 시, on opposite sides of the period), and 13:00 is the 24-hour trap.
HOUR_CASES: list[tuple[int, str]] = [
    (0, "오전 열두 시"),  # midnight is 오전 열두 시, not 오전 영 시
    (1, "오전 한 시"),  # attributive: not 하나 시
    (2, "오전 두 시"),  # not 둘 시
    (3, "오전 세 시"),  # not 셋 시
    (4, "오전 네 시"),  # not 넷 시
    (5, "오전 다섯 시"),
    (6, "오전 여섯 시"),
    (7, "오전 일곱 시"),
    (8, "오전 여덟 시"),
    (9, "오전 아홉 시"),
    (10, "오전 열 시"),
    (11, "오전 열한 시"),  # not 열하나 시
    (12, "오후 열두 시"),  # noon is 오후, not 오전
    (13, "오후 한 시"),  # not 오후 열세 시
    (14, "오후 두 시"),
    (15, "오후 세 시"),
    (16, "오후 네 시"),
    (17, "오후 다섯 시"),
    (18, "오후 여섯 시"),
    (19, "오후 일곱 시"),
    (20, "오후 여덟 시"),
    (21, "오후 아홉 시"),
    (22, "오후 열 시"),
    (23, "오후 열한 시"),
]

# The ticket's minute table, whole. None of these minutes is 0 or 30, so the readings do not
# touch them; the tests below still run each one under all four combinations.
MINUTE_CASES: list[tuple[time, str]] = [
    (time(15, 1), "오후 세 시 일 분"),
    (time(15, 5), "오후 세 시 오 분"),
    (time(15, 10), "오후 세 시 십 분"),  # not 일십
    (time(15, 15), "오후 세 시 십오 분"),
    (time(15, 20), "오후 세 시 이십 분"),
    (time(15, 35), "오후 세 시 삼십오 분"),
    (time(15, 44), "오후 세 시 사십사 분"),
    (time(15, 59), "오후 세 시 오십구 분"),
    (time(0, 5), "오전 열두 시 오 분"),  # five past midnight
    (time(4, 4), "오전 네 시 사 분"),  # same digit: native for the hour, Sino for the minute
    (time(12, 45), "오후 열두 시 사십오 분"),
    (time(23, 59), "오후 열한 시 오십구 분"),
]

# The ticket's readings table: (time, on_the_hour, half_past, expected). Where a reading does
# not apply to the minute, both of its values are listed, so the case holds under either.
READING_CASES: list[tuple[time, OnTheHour, HalfPast, str]] = [
    (time(15, 0), OnTheHour.BARE, HalfPast.BAN, "오후 세 시"),
    (time(15, 0), OnTheHour.BARE, HalfPast.MINUTES, "오후 세 시"),
    (time(15, 0), OnTheHour.JEONGGAK, HalfPast.BAN, "오후 세 시 정각"),
    (time(15, 0), OnTheHour.JEONGGAK, HalfPast.MINUTES, "오후 세 시 정각"),
    (time(0, 0), OnTheHour.JEONGGAK, HalfPast.BAN, "오전 열두 시 정각"),
    (time(0, 0), OnTheHour.JEONGGAK, HalfPast.MINUTES, "오전 열두 시 정각"),
    (time(15, 30), OnTheHour.BARE, HalfPast.BAN, "오후 세 시 반"),
    (time(15, 30), OnTheHour.JEONGGAK, HalfPast.BAN, "오후 세 시 반"),
    (time(15, 30), OnTheHour.BARE, HalfPast.MINUTES, "오후 세 시 삼십 분"),
    (time(15, 30), OnTheHour.JEONGGAK, HalfPast.MINUTES, "오후 세 시 삼십 분"),
    (time(12, 30), OnTheHour.BARE, HalfPast.BAN, "오후 열두 시 반"),
    (time(12, 30), OnTheHour.JEONGGAK, HalfPast.BAN, "오후 열두 시 반"),
]

# The twelve hour words, written literally, indexed by hour % 12: 0 and 12 are both 열두.
HOUR_WORDS: list[str] = [
    "열두",
    "한",
    "두",
    "세",
    "네",
    "다섯",
    "여섯",
    "일곱",
    "여덟",
    "아홉",
    "열",
    "열한",
]

READINGS: list[tuple[OnTheHour, HalfPast]] = [
    (on_the_hour, half_past) for on_the_hour in OnTheHour for half_past in HalfPast
]
READING_IDS = [f"{on_the_hour.value}-{half_past.value}" for on_the_hour, half_past in READINGS]

ALL_MINUTES_OF_THE_DAY: list[time] = [
    time(hour, minute) for hour in range(24) for minute in range(60)
]

# Composed Hangul syllables. A phrase made of anything else (a digit, a colon, a Latin letter,
# a jamo) is something MeloTTS would read out loud, or guess at.
HANGUL_SYLLABLES = range(0xAC00, 0xD7A4)

KOREAN_PACKAGE = "oral_korean.korean"


def label(moment: time) -> str:
    """A readable test id: 15:35."""
    return f"{moment.hour:02d}:{moment.minute:02d}"


@cache
def whole_day(on_the_hour: OnTheHour, half_past: HalfPast) -> dict[time, str]:
    """Every minute of the day rendered under one reading combination, computed once.

    Five sweeps read the same 1,440 texts per combination; rendering them once keeps the
    suite fast without letting any sweep skip a minute.
    """
    return {
        moment: render_time_of_day(moment, on_the_hour=on_the_hour, half_past=half_past)
        for moment in ALL_MINUTES_OF_THE_DAY
    }


def has_its_hour_word_before_si(moment: time, text: str) -> bool:
    """True when 시 is the third word, alone, after the literal hour word for `moment`."""
    words = text.split(" ")
    return (
        words.count("시") == 1
        and words.index("시") == 2
        and words[1] == HOUR_WORDS[moment.hour % 12]
    )


def depends_on_its_own_reading(moment: time) -> bool:
    """True when only the reading that owns `moment`'s minute changes its text.

    At :00 each `OnTheHour` value gives one text and the two give different texts, whatever
    `half_past` is; at :30 the same with `HalfPast`; at any other minute all four agree.
    """
    texts = {reading: whole_day(*reading)[moment] for reading in READINGS}
    if moment.minute == 0:
        owner, expected_distinct = 0, len(OnTheHour)
    elif moment.minute == 30:
        owner, expected_distinct = 1, len(HalfPast)
    else:
        return len(set(texts.values())) == 1
    by_owner = {(reading[owner], text) for reading, text in texts.items()}
    return len(by_owner) == expected_distinct == len(set(texts.values()))


# ---------------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------------


def test_on_the_hour_has_exactly_two_readings_with_stable_values() -> None:
    """The values are what T03 will carry through HTTP; a rename must fail here first."""
    assert [reading.name for reading in OnTheHour] == ["BARE", "JEONGGAK"]
    assert [reading.value for reading in OnTheHour] == ["bare", "jeonggak"]
    assert OnTheHour("bare") is OnTheHour.BARE
    assert OnTheHour("jeonggak") is OnTheHour.JEONGGAK


def test_half_past_has_exactly_two_readings_with_stable_values() -> None:
    """Same contract as `OnTheHour`: two members, constructible from their value."""
    assert [reading.name for reading in HalfPast] == ["BAN", "MINUTES"]
    assert [reading.value for reading in HalfPast] == ["ban", "minutes"]
    assert HalfPast("ban") is HalfPast.BAN
    assert HalfPast("minutes") is HalfPast.MINUTES


def test_render_time_of_day_keeps_its_agreed_signature() -> None:
    """The moment positional, both readings keyword-only: `(time, BARE, BAN)` cannot be written.

    Keyword-only is what stops the two readings being passed swapped by position.
    """
    assert signature_shape(render_time_of_day) == (["moment"], ["on_the_hour", "half_past"])


@pytest.mark.parametrize("name", ["on_the_hour", "half_past"])
def test_neither_reading_has_a_default(name: str) -> None:
    """Both readings are explicit choices of the caller, never a fallback inside the renderer.

    Read off the signature rather than by calling without them, which the type checker
    would (rightly) refuse to let this file do.
    """
    parameter = inspect.signature(render_time_of_day).parameters[name]

    assert parameter.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------------
# The ticket's tables
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "expected"), HOUR_CASES, ids=[f"{hour:02d}:00" for hour, _ in HOUR_CASES]
)
def test_every_hour_on_the_hour_with_the_bare_reading(hour: int, expected: str) -> None:
    """All 24 hours: the period, then the attributive native hour, then 시, and no minute word.

    Minute 0 renders as nothing at all: 세 시, never 세 시 영 분.
    """
    assert (
        render_time_of_day(time(hour, 0), on_the_hour=OnTheHour.BARE, half_past=HalfPast.BAN)
        == expected
    )


@pytest.mark.parametrize(
    ("hour", "expected"), HOUR_CASES, ids=[f"{hour:02d}:00" for hour, _ in HOUR_CASES]
)
def test_every_hour_on_the_hour_with_the_jeonggak_reading(hour: int, expected: str) -> None:
    """정각 is appended to the bare phrase at every hour, noon and midnight included."""
    assert (
        render_time_of_day(time(hour, 0), on_the_hour=OnTheHour.JEONGGAK, half_past=HalfPast.BAN)
        == f"{expected} 정각"
    )


@pytest.mark.parametrize(
    ("hour", "expected"), HOUR_CASES, ids=[f"{hour:02d}:30" for hour, _ in HOUR_CASES]
)
def test_every_hour_at_half_past_under_both_half_past_readings(hour: int, expected: str) -> None:
    """반 or 삼십 분 after the hour's phrase, at every hour of the day."""
    moment = time(hour, 30)

    assert (
        render_time_of_day(moment, on_the_hour=OnTheHour.BARE, half_past=HalfPast.BAN)
        == f"{expected} 반"
    )
    assert (
        render_time_of_day(moment, on_the_hour=OnTheHour.BARE, half_past=HalfPast.MINUTES)
        == f"{expected} 삼십 분"
    )


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
@pytest.mark.parametrize(
    ("moment", "expected"), MINUTE_CASES, ids=[label(moment) for moment, _ in MINUTE_CASES]
)
def test_minutes_render_in_sino_korean_under_every_reading(
    moment: time, expected: str, on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """The minute table, under all four readings: they touch :00 and :30 and nothing else.

    15:35 under each combination is the ticket's own case; the rest of the table rides along.
    """
    assert render_time_of_day(moment, on_the_hour=on_the_hour, half_past=half_past) == expected


@pytest.mark.parametrize(
    ("moment", "on_the_hour", "half_past", "expected"),
    READING_CASES,
    ids=[
        f"{label(moment)}-{on_the_hour.value}-{half_past.value}"
        for moment, on_the_hour, half_past, _ in READING_CASES
    ],
)
def test_the_readings_of_the_hour_and_the_half_hour(
    moment: time, on_the_hour: OnTheHour, half_past: HalfPast, expected: str
) -> None:
    """The readings table: each reading changes its own minute, and the other reading's
    value makes no difference to it (15:00 under both :30 readings, 15:30 under both :00)."""
    assert render_time_of_day(moment, on_the_hour=on_the_hour, half_past=half_past) == expected


# ---------------------------------------------------------------------------------
# Sweeps over all 1,440 minutes of the day, under each reading combination
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
def test_every_phrase_is_hangul_syllables_and_single_spaces(
    on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """No digit, no colon, no Latin letter, no jamo; no double, leading or trailing space.

    Digits are the trap: whether MeloTTS reads "3시 35분" with a native hour and Sino minutes
    is unverified, so the renderer must never hand it one.
    """
    malformed = [
        label(moment)
        for moment, text in whole_day(on_the_hour, half_past).items()
        if not text
        or text != text.strip(" ")
        or "  " in text
        or any(character != " " and ord(character) not in HANGUL_SYLLABLES for character in text)
    ]

    assert malformed == []


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
def test_every_phrase_starts_with_the_right_period(
    on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """오전 for hours 0 to 11, 오후 for 12 to 23, as the first word and not merely a prefix."""
    wrong = [
        label(moment)
        for moment, text in whole_day(on_the_hour, half_past).items()
        if text.split(" ")[0] != ("오전" if moment.hour < 12 else "오후")
    ]

    assert wrong == []


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
def test_the_word_before_si_is_the_right_hour_word(
    on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """시 appears exactly once, as the third word, after the literal hour word for its hour.

    One of the twelve words is the ticket's floor; checking it is the right one for the hour
    (열두 at 0 and 12, 한 at 1 and 13, ...) also catches an hour that shifts with the minute.
    """
    wrong = [
        label(moment)
        for moment, text in whole_day(on_the_hour, half_past).items()
        if not has_its_hour_word_before_si(moment, text)
    ]

    assert wrong == []


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
def test_the_minutes_come_from_the_sino_korean_renderer(
    on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """After 시, every minute other than 0 and 30 is its Sino-Korean numeral, then 분.

    `render_number` is the oracle here because the ticket names it as the minutes' source,
    and `test_numerals.py` pins its table independently of this module.
    """
    wrong = [
        label(moment)
        for moment, text in whole_day(on_the_hour, half_past).items()
        if moment.minute not in (0, 30)
        and text.split(" ")[3:] != [render_number(moment.minute, NumeralSystem.SINO), "분"]
    ]

    assert wrong == []


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
def test_yeong_never_appears(on_the_hour: OnTheHour, half_past: HalfPast) -> None:
    """Neither minute 0 nor midnight's hour is ever spoken as 영.

    Checked as a syllable, not only as a word: no word of a correct phrase contains 영.
    """
    spoken = [
        label(moment) for moment, text in whole_day(on_the_hour, half_past).items() if "영" in text
    ]

    assert spoken == []


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
def test_no_two_minutes_of_the_day_sound_the_same(
    on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """1,440 distinct phrases: two times sounding alike would make a question unanswerable.

    Dropping the period, or reading 00:xx and 12:xx the same way, is what this catches.
    """
    texts = list(whole_day(on_the_hour, half_past).values())

    assert len(texts) == 1440
    assert len(set(texts)) == 1440


def test_the_readings_change_only_minutes_zero_and_thirty() -> None:
    """Across the whole day, the four combinations agree everywhere except :00 and :30.

    And at :00 only `on_the_hour` matters, at :30 only `half_past`: a reading leaking into
    the other's minute shows up here even where the readings table has no case.
    """
    leaked = [
        label(moment) for moment in ALL_MINUTES_OF_THE_DAY if not depends_on_its_own_reading(moment)
    ]

    assert leaked == []


# ---------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("on_the_hour", "half_past"), READINGS, ids=READING_IDS)
@pytest.mark.parametrize(
    "moment",
    [
        time(15, 35, 10),
        time(15, 35, 0, 1),
        time(15, 35, 59, 999_999),
        time(0, 0, 1),
    ],
    ids=["seconds", "one-microsecond", "last-microsecond-of-the-minute", "midnight-plus-a-second"],
)
def test_a_time_with_seconds_or_microseconds_is_refused(
    moment: time, on_the_hour: OnTheHour, half_past: HalfPast
) -> None:
    """Refused, not truncated: 15:35:10 must not quietly become 오후 세 시 삼십오 분.

    Under every reading, since 00:00:01 with 정각 would otherwise be a confident lie.
    """
    with pytest.raises(ValueError):
        render_time_of_day(moment, on_the_hour=on_the_hour, half_past=half_past)


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(24, 0), (15, 60), (-1, 0), (15, -1)],
    ids=["24:00", "15:60", "-1:00", "15:-1"],
)
def test_an_impossible_time_is_refused(hour: int, minute: int) -> None:
    """Hour 24 and minute 60 are refused, whichever layer does it.

    With `datetime.time` as the input, its own constructor refuses them before the renderer
    is reached, which satisfies the contract: no text is ever produced for them.
    """
    with pytest.raises(ValueError):
        render_time_of_day(
            time(hour, minute), on_the_hour=OnTheHour.BARE, half_past=HalfPast.BAN
        )


def test_a_time_with_a_time_zone_is_refused() -> None:
    """The phrase has no zone, so an aware time is refused rather than read as if naive."""
    with pytest.raises(ValueError):
        render_time_of_day(
            time(15, 35, tzinfo=UTC), on_the_hour=OnTheHour.BARE, half_past=HalfPast.BAN
        )


@pytest.mark.parametrize(
    ("on_the_hour", "half_past"),
    [("martian", HalfPast.BAN), (OnTheHour.BARE, "martian")],
    ids=["on-the-hour", "half-past"],
)
def test_an_unknown_reading_is_refused(on_the_hour: object, half_past: object) -> None:
    """Refused like an unknown numeral system, never read as one of the known readings."""
    with pytest.raises(ValueError):
        render_time_of_day(
            time(15, 0),
            on_the_hour=cast(OnTheHour, on_the_hour),
            half_past=cast(HalfPast, half_past),
        )


# ---------------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------------


def test_the_module_imports_nothing_forbidden() -> None:
    """No TTS, no HTTP, no storage, no network: the shared forbidden list, applied here."""
    imported = imported_module_names(time_of_day)

    assert sorted(name for name in imported if name.startswith(FORBIDDEN_IMPORTS)) == []


def test_the_module_stays_inside_korean_and_the_standard_library() -> None:
    """From the project, only `oral_korean.korean`; from outside it, only the standard library.

    `test_layering.py` already keeps `korean/` away from the rest of the project; the
    stricter half here is the standard library: no third-party dependency for a phrase.
    """
    imported = imported_module_names(time_of_day)

    outside_korean = sorted(
        name
        for name in imported
        if (name == "oral_korean" or name.startswith("oral_korean."))
        and not (name == KOREAN_PACKAGE or name.startswith(f"{KOREAN_PACKAGE}."))
    )
    third_party = sorted(
        name
        for name in imported
        if name.split(".")[0] not in sys.stdlib_module_names and name.split(".")[0] != "oral_korean"
    )

    assert outside_korean == []
    assert third_party == []


def test_the_module_builds_on_the_numerals_module() -> None:
    """The hour word and the minutes come from `numerals.py`, not from a table of their own.

    The whole-day sweeps pin the text; this pins where it comes from, so a second copy of the
    attributive forms cannot drift from the one `test_numerals.py` protects.
    """
    assert "oral_korean.korean.numerals" in imported_module_names(time_of_day)
