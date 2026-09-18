"""Korean numerals: turning an integer into the word a Korean speaker would say.

Two systems live here side by side, and neither is a special case of the other:

- **Sino-Korean** (영, 일, 이, 삼 ...) - prices, dates, phone numbers, addresses. Grouped
  by 10,000 (만) rather than by 1,000, and the leading 일 is dropped on 십/백/천/만.
- **Native Korean** (하나, 둘, 셋 ...) - counting things, ages, hours. Irregular tens, no
  zero, and conventionally no word past 99.

Dates, time and prices will all need this, which is why it sits in `korean/` rather than
inside one exercise. The module is pure: no file I/O, no HTTP, no TTS import, so the
riskiest logic in the project is testable without a single mock.

The supported range of each system lives here too, and nowhere else. `config.py` was the
other candidate and is the wrong home: it holds environment-driven runtime settings, while
"native Korean has no zero and stops at 99" is a fact about the language that no
deployment may override.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class NumeralError(ValueError):
    """A number could not be rendered in the system it was asked for.

    One error type for every refusal - a value the system cannot express, a value that is
    not an integer, an unrecognised system - so the HTTP layer maps the whole family onto
    one response. It subclasses `ValueError` because that is what it is.
    """


class NumeralSystem(StrEnum):
    """Which set of Korean numerals to speak in.

    A `StrEnum` so that a query parameter can become a member by value, with no lookup
    table of its own at the HTTP boundary, and so the values stay stable on the wire.
    """

    SINO = "sino"
    NATIVE = "native"


DEFAULT_NUMERAL_SYSTEM: Final = NumeralSystem.SINO
"""The system to practise unless the caller says otherwise.

A named constant rather than a parameter default, so the fallback happens once, visibly,
at the boundary that should make it, instead of silently inside the renderer.
"""


@dataclass(frozen=True)
class NumberRange:
    """An inclusive range of integers, both ends named.

    Named fields rather than a bare tuple: a transposed pair of bounds is caught by
    nothing at runtime, and `(1, 99)` at a call site tells the reader which is which only
    by convention.
    """

    minimum: int
    maximum: int


_SUPPORTED_RANGES: Final[dict[NumeralSystem, NumberRange]] = {
    # Sino-Korean reaches far higher than this; 100 is where the *exercise* stops for now,
    # and 0 is included because 영 is a real word the listener may as well learn.
    NumeralSystem.SINO: NumberRange(0, 100),
    # Native Korean's bounds are the language's, not a product decision: no zero, and no
    # conventional word past 99.
    NumeralSystem.NATIVE: NumberRange(1, 99),
}

# How far `render_number` will go in Sino-Korean, which is deliberately further than the
# exercise draws from but not unbounded. Past 만 the readings need 억 and 조, and whether
# those keep their leading 일 (일억, unlike 만) is not something this project has
# verified. Rendering them on a guess is exactly the silent failure this module exists to
# avoid, so anything from 100,000,000 up is refused instead.
_SINO_RENDER_CEILING: Final = 100_000_000

_SINO_ZERO: Final = "영"
_SINO_DIGITS: Final = ("", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구")
# Ordered most significant first, which is the order they are spoken in.
_SINO_PLACES: Final = ((1000, "천"), (100, "백"), (10, "십"))
_SINO_MYRIAD: Final = "만"

_NATIVE_UNITS: Final = ("", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉")
_NATIVE_TENS: Final = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")


def supported_range(system: NumeralSystem) -> NumberRange:
    """Return the inclusive range a question may be drawn from in `system`.

    Callers ask instead of hardcoding a ceiling, which is what keeps the native-Korean 99
    from being repeated into a route, a validator and a UI control that then drift apart.

    Raises:
        NumeralError: `system` is not a `NumeralSystem`. There is no fallback to
            Sino-Korean: silently answering the wrong question is worse than refusing.
    """
    if not isinstance(system, NumeralSystem):
        raise NumeralError(f"Unknown numeral system {system!r}.")
    return _SUPPORTED_RANGES[system]


def render_number(value: int, system: NumeralSystem) -> str:
    """Return `value` written as Korean text in `system`.

    The rendering domain is wider than `supported_range` for Sino-Korean: the exercise
    stops at 100, while the renderer goes as far as it has been verified to, so dates and
    prices can reuse it later. For native Korean the two coincide, because 1 to 99 is all
    the language offers.

    Args:
        value: the integer to render. A float is refused even when it is whole: a
            renderer that accepts 42.0 is one JSON payload away from speaking 42.0000001
            as 사십이.
        system: which numerals to use. No default, so the choice is always explicit.

    Raises:
        NumeralError: `system` is unknown, `value` is not an integer, or `value` is
            outside what `system` can express. Never a clamp, and never a
            wrong-but-plausible string.
    """
    if not isinstance(system, NumeralSystem):
        raise NumeralError(f"Unknown numeral system {system!r}.")
    if not isinstance(value, int):
        raise NumeralError(
            f"Cannot render {value!r} in {system.value}-Korean: expected an integer, "
            f"got {type(value).__name__}."
        )

    if system is NumeralSystem.NATIVE:
        return _render_native(value)
    return _render_sino(value)


def _render_native(value: int) -> str:
    """Render 1 to 99 in native Korean, irregular tens included."""
    span = _SUPPORTED_RANGES[NumeralSystem.NATIVE]
    if not span.minimum <= value <= span.maximum:
        raise NumeralError(
            f"Cannot render {value} in native-Korean numerals: the system has no zero and "
            f"stops at 99, so it only covers {span.minimum} to {span.maximum}."
        )

    tens, units = divmod(value, 10)
    return _NATIVE_TENS[tens] + _NATIVE_UNITS[units]


def _render_sino(value: int) -> str:
    """Render 0 up to the verified ceiling in Sino-Korean, grouped by 10,000."""
    if not 0 <= value < _SINO_RENDER_CEILING:
        raise NumeralError(
            f"Cannot render {value} in sino-Korean numerals: this renderer covers "
            f"0 to {_SINO_RENDER_CEILING - 1}."
        )
    if value == 0:
        return _SINO_ZERO

    myriads, remainder = divmod(value, 10_000)
    if myriads == 0:
        return _render_sino_myriad(remainder)

    # 만 on its own, never 일만 - the same rule as 십/백/천, one magnitude up.
    head = _SINO_MYRIAD if myriads == 1 else _render_sino_myriad(myriads) + _SINO_MYRIAD
    tail = _render_sino_myriad(remainder) if remainder else ""
    return head + tail


def _render_sino_myriad(value: int) -> str:
    """Render 1 to 9999, one 만-group, in Sino-Korean.

    A place whose digit is zero contributes nothing at all rather than 영, which is why
    1004 is 천사 and not 천영백영십사.
    """
    spoken: list[str] = []
    remainder = value
    for place, unit in _SINO_PLACES:
        digit, remainder = divmod(remainder, place)
        if digit:
            # 십 rather than 일십, 백 rather than 일백, 천 rather than 일천.
            spoken.append(_SINO_DIGITS[digit] + unit if digit > 1 else unit)
    if remainder:
        spoken.append(_SINO_DIGITS[remainder])
    return "".join(spoken)
