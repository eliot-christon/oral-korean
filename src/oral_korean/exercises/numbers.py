"""The number-recognition exercise: draw a number to speak, judge what was typed back.

Two functions and three small value types, deliberately not a class hierarchy: the shared
shape of an exercise is what a *second* exercise type reveals, and inventing it now would
be guessing. Like `korean/`, this module is pure - it decides what to say and whether an
answer is right, and knows nothing about audio, HTTP or storage.

Answers are typed as digits in both numeral systems, so judging is system-independent.
The system decides what is spoken and what is shown back after a miss, nothing more.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from oral_korean.korean.numerals import NumberRange, NumeralSystem, render_number, supported_range


class InvalidRangeError(ValueError):
    """A question was asked for over a range the active system cannot serve.

    Raised rather than clamped: a native-Korean request for 1 to 100 quietly reduced to
    1 to 99 is a caller that goes on believing it asked for something else. It subclasses
    `ValueError`, like `NumeralError`, so one `except` covers every bad request here.
    """


@dataclass(frozen=True)
class NumberQuestion:
    """One drawn question: the number, the Korean to speak, and the system it came from.

    Frozen because it is an answer key. Questions outlive the request that created them
    (the HTTP layer keeps the pending ones), and a mutable answer key is a rewritable one.

    Attributes:
        number: the integer the listener has to recognise.
        text: the Korean to be spoken. Named `text` because that is what the speech layer
            already calls what it synthesises.
        system: the numerals `text` is written in, carried along so no later caller has to
            remember which system the question was drawn with.
    """

    number: int
    text: str
    system: NumeralSystem


class Verdict(StrEnum):
    """How an answer turned out.

    Three outcomes rather than a boolean, because "you typed nothing recognisable" is not
    the same feedback as "that is the wrong number", and a caller that cannot tell them
    apart will show the wrong message for one of them.
    """

    CORRECT = "correct"
    INCORRECT = "incorrect"
    NOT_A_NUMBER = "not_a_number"


@dataclass(frozen=True)
class Judgement:
    """The verdict on one answer, with everything needed to show feedback.

    Attributes:
        verdict: correct, incorrect, or not a number at all.
        expected_number: the number that was actually drawn.
        text: the Korean that was spoken for it.

    Both the number and the text are carried on every verdict, including
    `NOT_A_NUMBER`, so the caller shows the same feedback whichever way the answer missed.
    """

    verdict: Verdict
    expected_number: int
    text: str


def draw_number_question(
    system: NumeralSystem,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    rng: random.Random | None = None,
) -> NumberQuestion:
    """Draw a number in `system` and return it with the Korean text to speak.

    Args:
        system: which numerals to draw and render in.
        minimum: the lowest number that may be drawn; `None` means the system's own
            lowest. Keyword-only, so a transposed pair of bounds cannot slip past as two
            interchangeable positional integers.
        maximum: the highest number that may be drawn, inclusive; `None` means the
            system's own highest. Omitting both is how a caller asks a valid question
            without knowing the ceiling.
        rng: the random source to draw from. Injected so a test can seed it; the stdlib
            `random.Random` is already the seam, so no protocol is invented for it.

    Raises:
        NumeralError: `system` is not a known numeral system.
        InvalidRangeError: the resolved range is empty, or reaches outside what `system`
            supports. Validation is against the *active* system, which is why 1 to 100 is
            a fine Sino-Korean request and not a native-Korean one.
    """
    span = supported_range(system)
    resolved = NumberRange(
        minimum=span.minimum if minimum is None else minimum,
        maximum=span.maximum if maximum is None else maximum,
    )

    if resolved.minimum > resolved.maximum:
        raise InvalidRangeError(
            f"Empty range for {system.value}-Korean: minimum {resolved.minimum} is above "
            f"maximum {resolved.maximum}."
        )
    if resolved.minimum < span.minimum or resolved.maximum > span.maximum:
        raise InvalidRangeError(
            f"{system.value}-Korean questions can only be drawn from {span.minimum} to "
            f"{span.maximum}, so {resolved.minimum} to {resolved.maximum} is out of reach."
        )

    source = random.Random() if rng is None else rng
    number = source.randint(resolved.minimum, resolved.maximum)
    return NumberQuestion(
        number=number, text=render_number(number, system), system=system
    )


def judge_answer(question: NumberQuestion, answer: str) -> Judgement:
    """Decide whether `answer` is what `question` asked for.

    Takes the whole question rather than a loose number, so the result can carry the text
    that was spoken without the caller having to hand it back in.

    Args:
        question: the question that was asked.
        answer: exactly what the listener typed, untrimmed.

    Returns:
        A `Judgement` carrying the verdict, the expected number and its Korean text. It
        never raises: an unusable answer is a verdict, not an error.
    """
    verdict = _verdict_for(question.number, answer)
    return Judgement(verdict=verdict, expected_number=question.number, text=question.text)


def _verdict_for(expected: int, answer: str) -> Verdict:
    """Classify `answer` against `expected`, after trimming surrounding whitespace.

    An answer counts as a number only when it is ASCII digits and nothing else. `int()`
    on its own is too generous for this: it reads "4_2" as 42, so a typo would be scored
    as a right answer - the one failure this exercise must never have. The same rule is
    what makes "4 2", "42.0" and "-42" unparseable rather than wrong.

    A number this exercise would never ask (999999999999) is still a *number*, so it is
    incorrect rather than unparseable: "that is not a number" should describe what was
    typed, not how unlikely it was.
    """
    trimmed = answer.strip()
    if not (trimmed.isascii() and trimmed.isdigit()):
        return Verdict.NOT_A_NUMBER
    # Leading zeros are the same number, which is why this is a comparison of integers
    # and not of strings.
    return Verdict.CORRECT if int(trimmed) == expected else Verdict.INCORRECT
