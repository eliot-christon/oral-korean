"""Tests for Korean numeral rendering: both systems, the range each supports, its refusals.

Framing-mode note: none of the production code below exists yet. These tests are written
from T03's acceptance criteria and test contract, and they define the contract the
implementation must satisfy:

- `oral_korean.korean.numerals.NumeralSystem` - an enum with exactly two members, `SINO`
  (value "sino") and `NATIVE` (value "native"), constructible from its value so T04 can
  take it straight off a query string. `StrEnum` is the recommended base; nothing here
  requires more than `str` values and by-value lookup.
- `oral_korean.korean.numerals.DEFAULT_NUMERAL_SYSTEM` - `NumeralSystem.SINO`, the
  documented default. A named constant rather than a parameter default, so the fallback
  is visible at the one boundary that should make it (T04's HTTP layer) instead of
  happening silently inside the renderer.
- `oral_korean.korean.numerals.render_number(value: int, system: NumeralSystem) -> str` -
  the rendering function. `system` has no default, for the same reason.
- `oral_korean.korean.numerals.NumberRange` - a frozen dataclass whose fields are
  `minimum` then `maximum`.
- `oral_korean.korean.numerals.supported_range(system: NumeralSystem) -> NumberRange` -
  the range a question may be drawn from in that system. Native is exactly 1 to 99, Sino
  is 0 to 100. These two numbers live here and nowhere else: `config.py` was the other
  candidate and is the wrong home, because it holds environment-driven runtime settings
  (host, port, paths, voice) while "native Korean has no zero and stops at 99" is a fact
  about the language that no deployment may override.
- `oral_korean.korean.numerals.NumeralError(ValueError)` - the single error type for a
  value the system cannot express, a non-integer value, or an unknown system. It
  subclasses `ValueError` so T04 can map the whole family onto one HTTP 400.

Two decisions the ticket leaves open, taken here rather than silently:

1. **The renderer's domain is wider than the supported range, for Sino only.** The
   ticket's own table requires 0 (영), 10000 (만) and 12345 to render, while its exercise
   range stops at 100 ("the renderer handles more; the exercise range does not need it
   yet"). So `render_number` refuses only what Sino-Korean cannot express - a negative, a
   non-integer, or a value past its render ceiling - while `supported_range` reports what
   a question may be drawn from. For native Korean the two coincide at 1 to 99, which is
   why every rejection in the tables below is a native one.
2. **The Sino renderer's ceiling turned out to be 100,000,000, exclusive, and that is now
   pinned rather than left open.** The framing round of this file left the renderer's
   upper reach unasserted; the implementation drew the line explicitly instead, because
   past 만 the readings need 억 and 조, and whether those keep a leading 일 (일억, unlike
   만) is unverified by this project. Guessing would be exactly the silent wrong-Korean
   failure this module exists to prevent, so both the highest accepted value and the
   first refused one are asserted below.
3. **`supported_range(SINO).minimum` is 0, not the 1 of the acceptance criteria.** The
   drawing contract requires the range 0 to 10 to be accepted under Sino and rejected
   under native, and separately requires a bound outside the supported range to be
   rejected. Those two are only consistent if 0 is inside Sino's supported range, and 영
   is a real Sino-Korean word, so it costs nothing.

Everything here is a pure function call: no file I/O, no network, no TTS, no patching.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import cast

import pytest
from conftest import signature_shape

from oral_korean.korean.numerals import (
    DEFAULT_NUMERAL_SYSTEM,
    NumberRange,
    NumeralError,
    NumeralSystem,
    render_number,
    supported_range,
)

# Sino-Korean: every case the ticket lists, plus the units and the 만 groupings its table
# skips. Grouped by 10,000 and dropping the leading 일 on 십/백/천 are the two rules a
# wrong implementation gets wrong silently, so both are exercised at several magnitudes.
SINO_CASES: list[tuple[int, str]] = [
    (0, "영"),
    (1, "일"),
    (2, "이"),
    (3, "삼"),
    (4, "사"),
    (5, "오"),
    (6, "육"),
    (7, "칠"),
    (8, "팔"),
    (9, "구"),
    (10, "십"),  # not 일십
    (11, "십일"),
    (15, "십오"),
    (20, "이십"),
    (42, "사십이"),
    (90, "구십"),
    (99, "구십구"),
    (100, "백"),  # not 일백
    (101, "백일"),
    (110, "백십"),
    (200, "이백"),
    (555, "오백오십오"),
    (1000, "천"),  # not 일천
    (1004, "천사"),  # the empty hundreds and tens vanish rather than becoming 영
    (1100, "천백"),
    (10000, "만"),  # not 일만
    (12345, "만이천삼백사십오"),
    (20000, "이만"),
    (100000, "십만"),
]

# Native Korean: the ticket's table plus the units it stops short of (6 to 9) and one
# compound per irregular ten. The tens are the irregular part and a copy-paste from the
# Sino table would sail through a units-only test.
NATIVE_CASES: list[tuple[int, str]] = [
    (1, "하나"),
    (2, "둘"),
    (3, "셋"),
    (4, "넷"),
    (5, "다섯"),
    (6, "여섯"),
    (7, "일곱"),
    (8, "여덟"),
    (9, "아홉"),
    (10, "열"),
    (11, "열하나"),
    (12, "열둘"),
    (15, "열다섯"),
    (19, "열아홉"),
    (20, "스물"),
    (21, "스물하나"),
    (29, "스물아홉"),
    (30, "서른"),
    (33, "서른셋"),
    (40, "마흔"),
    (42, "마흔둘"),
    (44, "마흔넷"),
    (50, "쉰"),
    (55, "쉰다섯"),
    (60, "예순"),
    (68, "예순여덟"),
    (70, "일흔"),
    (71, "일흔하나"),
    (80, "여든"),
    (87, "여든일곱"),
    (90, "아흔"),
    (95, "아흔다섯"),
    (99, "아흔아홉"),
]

SYSTEMS = list(NumeralSystem)
SYSTEM_IDS = [system.name.lower() for system in SYSTEMS]

# Composed Hangul syllables. A rendering made of anything else (a stray digit, a Latin
# letter, a jamo) is a bug the exercise would happily read out loud.
HANGUL_SYLLABLES = range(0xAC00, 0xD7A4)


def is_hangul_word(text: str) -> bool:
    """True when `text` is non-empty and made only of composed Hangul syllables."""
    return bool(text) and all(ord(character) in HANGUL_SYLLABLES for character in text)


# ---------------------------------------------------------------------------------
# The numeral system itself
# ---------------------------------------------------------------------------------


def test_numeral_system_has_exactly_two_members_with_wire_friendly_values() -> None:
    """The members and their values are the contract T04 threads through HTTP.

    By-value construction is what lets a query parameter become a `NumeralSystem` with no
    lookup table of its own, and pinning the values here means a later rename shows up as
    a failing test rather than a frontend that silently stops selecting a system.
    """
    assert [system.name for system in NumeralSystem] == ["SINO", "NATIVE"]
    assert [system.value for system in NumeralSystem] == ["sino", "native"]
    assert NumeralSystem("sino") is NumeralSystem.SINO
    assert NumeralSystem("native") is NumeralSystem.NATIVE


def test_sino_korean_is_the_documented_default() -> None:
    """The default is a named constant, so callers opt into it explicitly."""
    assert DEFAULT_NUMERAL_SYSTEM is NumeralSystem.SINO


def test_numeral_error_is_a_value_error() -> None:
    """One family to catch: T04 turns any `ValueError` from here into a 400."""
    assert issubclass(NumeralError, ValueError)


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        (render_number, ["value", "system"], []),
        (supported_range, ["system"], []),
    ],
    ids=["render_number", "supported_range"],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """Parameter names and order are the contract, not an accident of the first draft."""
    assert signature_shape(function) == (positional, keyword_only)


# ---------------------------------------------------------------------------------
# Rendering: Sino-Korean
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), SINO_CASES, ids=[f"sino-{value}" for value, _ in SINO_CASES]
)
def test_sino_korean_rendering(value: int, expected: str) -> None:
    """The Sino-Korean table. A wrong entry here is the ticket's silent failure mode."""
    assert render_number(value, NumeralSystem.SINO) == expected


def test_sino_korean_renders_the_highest_value_below_its_ceiling() -> None:
    """One below the render ceiling: still two full 만-groups, still 9999 twice over.

    99,999,999 is 9999만9999 - the last value this renderer accepts before 억 would be
    needed, and the one case above pinning the ceiling would leave untested.
    """
    assert render_number(99_999_999, NumeralSystem.SINO) == "구천구백구십구만구천구백구십구"


# ---------------------------------------------------------------------------------
# Rendering: native Korean
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), NATIVE_CASES, ids=[f"native-{value}" for value, _ in NATIVE_CASES]
)
def test_native_korean_rendering(value: int, expected: str) -> None:
    """The native-Korean table, irregular tens included."""
    assert render_number(value, NumeralSystem.NATIVE) == expected


# ---------------------------------------------------------------------------------
# Cross-system and bounds
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [20, 42], ids=["20", "42"])
def test_the_two_systems_render_the_same_number_differently(value: int) -> None:
    """One table copy-pasted into the other would pass every case above but fail here."""
    sino = render_number(value, NumeralSystem.SINO)
    native = render_number(value, NumeralSystem.NATIVE)

    assert sino != native
    assert is_hangul_word(sino)
    assert is_hangul_word(native)


def test_each_system_reports_the_range_it_supports() -> None:
    """Callers ask instead of hardcoding a ceiling; native's is exact, Sino's is a floor.

    Native is pinned to exactly 1 to 99 because that bound is a fact about the language.
    Sino is only required to reach 100, since the ticket explicitly leaves room to raise
    the exercise ceiling later without touching this test.
    """
    native = supported_range(NumeralSystem.NATIVE)
    sino = supported_range(NumeralSystem.SINO)

    assert (native.minimum, native.maximum) == (1, 99)
    assert sino.maximum >= 100
    assert sino.minimum <= 0
    assert sino != native


@pytest.mark.parametrize("field_name", ["minimum", "maximum"], ids=["minimum", "maximum"])
def test_a_supported_range_is_an_immutable_named_pair(field_name: str) -> None:
    """A frozen dataclass with named fields: a bare tuple invites a transposed bound."""
    span = supported_range(NumeralSystem.NATIVE)

    assert [field.name for field in dataclasses.fields(span)] == ["minimum", "maximum"]
    assert isinstance(span, NumberRange)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(span, field_name, 7)


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_every_supported_value_renders_to_its_own_hangul_word(system: NumeralSystem) -> None:
    """Sweep the whole supported range: every value speakable, and no two alike.

    Two numbers rendering to the same string is the worst silent bug available here - the
    exercise would speak one number and accept the other - and no spot check catches it.
    """
    span = supported_range(system)
    rendered = {
        value: render_number(value, system) for value in range(span.minimum, span.maximum + 1)
    }

    assert [value for value, text in rendered.items() if not is_hangul_word(text)] == []
    assert len(set(rendered.values())) == len(rendered)


# ---------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 100, 101, 1000], ids=["zero", "hundred", "101", "1000"])
def test_native_korean_rejects_values_outside_its_range(value: int) -> None:
    """Native Korean has no zero and stops at 99, and says so when asked for more.

    The message has to name the system and both bounds: this string is what T04 shows a
    caller who asked for the wrong thing, and "invalid value" would tell them nothing.
    """
    with pytest.raises(NumeralError) as excinfo:
        render_number(value, NumeralSystem.NATIVE)

    message = str(excinfo.value).lower()
    assert "native" in message
    assert "1" in message
    assert "99" in message


def test_sino_korean_refuses_the_first_value_past_its_ceiling() -> None:
    """One past the ceiling, where 억 would be needed and this renderer will not guess.

    The message has to say where the renderer stops, for the same reason the
    native-Korean refusal names its bounds: a caller hitting this needs to know the
    renderer's actual reach, not just that something was rejected.
    """
    with pytest.raises(NumeralError) as excinfo:
        render_number(100_000_000, NumeralSystem.SINO)

    message = str(excinfo.value).lower()
    assert "sino" in message
    assert "99999999" in message


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
@pytest.mark.parametrize("value", [-1, -42], ids=["-1", "-42"])
def test_negative_values_are_rejected_in_both_systems(value: int, system: NumeralSystem) -> None:
    """A minus sign is not a numeral: no 마이너스, no dropped sign, an error."""
    with pytest.raises(NumeralError) as excinfo:
        render_number(value, system)

    assert system.name.lower() in str(excinfo.value).lower()


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
@pytest.mark.parametrize("value", [4.5, 42.0], ids=["4.5", "42.0"])
def test_non_integer_values_are_rejected_in_both_systems(
    value: float, system: NumeralSystem
) -> None:
    """Not truncated, not rounded, not quietly accepted because it happens to be whole.

    42.0 is in the table as well as 4.5: a renderer that takes floats is one JSON payload
    away from rendering 42.0000001 as 사십이. `cast` rather than a type-ignore because the
    value really does arrive untyped at runtime, and mypy must not be told otherwise.
    """
    with pytest.raises(NumeralError):
        render_number(cast(int, value), system)


@pytest.mark.parametrize(
    "system",
    ["martian", "SINO", "", 0, None],
    ids=["unknown-name", "wrong-case", "empty", "integer", "none"],
)
def test_an_unknown_system_is_rejected_rather_than_falling_back(system: object) -> None:
    """No silent fallback to Sino: an unrecognised system is an error, both ways in."""
    with pytest.raises(NumeralError):
        render_number(42, cast(NumeralSystem, system))

    with pytest.raises(NumeralError):
        supported_range(cast(NumeralSystem, system))
