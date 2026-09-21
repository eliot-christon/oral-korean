"""Tests for the number exercise: drawing a question in a system, and judging an answer.

Framing-mode note: none of the production code below exists yet. These tests are written
from T03's acceptance criteria and test contract, and they define the contract the
implementation must satisfy:

- `oral_korean.exercises.numbers.NumberQuestion` - a frozen dataclass whose fields are
  `number: int`, `text: str` and `system: NumeralSystem`, in that order. It carries the
  system it was drawn with so no later caller has to remember it, and `text` is the
  Korean to be spoken (the same name the TTS layer already uses for what it synthesises).
- `oral_korean.exercises.numbers.draw_number_question(system: NumeralSystem, *,
  minimum: int | None = None, maximum: int | None = None, rng: random.Random | None =
  None) -> NumberQuestion`. The bounds are keyword-only and independently optional: each
  one left out falls back to the corresponding bound of `supported_range(system)`, so a
  caller never has to know the ceiling. `rng` is a plain `random.Random`, injected as a
  parameter - the stdlib already provides the seam, so no Protocol is invented for it and
  no test patches `random`.
- `oral_korean.exercises.numbers.InvalidRangeError(ValueError)` - raised for every range
  the active system cannot serve: minimum above maximum, or a bound outside the system's
  supported range. Its message names the system and that range.
- `oral_korean.exercises.numbers.Verdict` - an enum with exactly three members, `CORRECT`
  ("correct"), `INCORRECT` ("incorrect") and `NOT_A_NUMBER` ("not_a_number"). `StrEnum`
  is the recommended base, for the same wire reasons as `NumeralSystem`.
- `oral_korean.exercises.numbers.Judgement` - a frozen dataclass whose fields are
  `verdict: Verdict`, `expected_number: int` and `text: str`, in that order. Every
  verdict carries both, including `NOT_A_NUMBER`, so feedback never depends on which way
  the answer was wrong.
- `oral_korean.exercises.numbers.judge_answer(question: NumberQuestion, answer: str) ->
  Judgement`. Taking the whole question rather than a loose number plus text is what lets
  the result carry the spoken text without the caller passing it back in.

Decisions taken here that the ticket leaves open, flagged in the hand-back report:

- **An answer is accepted only when it is ASCII digits, after trimming.** That is what
  makes "4 2", "42.0" and "-42" not-a-number, and it also catches "4_2", which a bare
  `int()` would happily read as 42 (Python allows underscore separators) and mark
  correct - a typo silently scored as a right answer is exactly this ticket's failure
  mode. Full-width digits ("４２") are deliberately not tested either way; see the report.
- **An out-of-range answer is a wrong number, not a non-number.** "999999999999" judges
  INCORRECT: "not a number" means the input was not a number, not that it was implausible.
- **The 200-draw tests assert spread rather than exact bounds.** Requiring min == 1 and
  max == 100 from 200 uniform draws fails about a quarter of the time, which is a flaky
  test, not a strict one. In-range is asserted exactly; reachability of both bounds gets
  its own deterministic-enough test over a two-value range.

Both modules under test are pure: no file I/O, no network, no TTS import, no patching.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Callable
from typing import cast

import pytest
from conftest import signature_shape

from oral_korean.exercises.numbers import (
    InvalidRangeError,
    Judgement,
    NumberQuestion,
    Verdict,
    draw_number_question,
    judge_answer,
)
from oral_korean.korean.numerals import NumeralSystem, render_number, supported_range

# The number every judging test is about, and a seed for the draws that need to be
# reproducible. Both systems can render 42, which is what makes the cross-system judging
# cases comparable.
ANSWER_NUMBER = 42
SEED = 20260918
SAMPLE_SIZE = 200

SYSTEMS = list(NumeralSystem)
SYSTEM_IDS = [system.name.lower() for system in SYSTEMS]


def seeded() -> random.Random:
    """A fresh random source at a fixed seed.

    Fresh per call on purpose: a shared instance advances its state between draws, so two
    draws meant to be compared would start from different places and prove nothing.
    """
    return random.Random(SEED)


def make_question(system: NumeralSystem, number: int = ANSWER_NUMBER) -> NumberQuestion:
    """Draw the question for exactly `number`, by pinning the range to it.

    Going through the real draw rather than building a `NumberQuestion` by hand keeps the
    judging tests honest: they judge the object production actually produces.
    """
    return draw_number_question(system, minimum=number, maximum=number, rng=seeded())


def judge(system: NumeralSystem, answer: str) -> Judgement:
    """Judge `answer` against a freshly drawn question for 42 in `system`."""
    return judge_answer(make_question(system), answer)


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        (draw_number_question, ["system"], ["minimum", "maximum", "rng"]),
        (judge_answer, ["question", "answer"], []),
    ],
    ids=["draw_number_question", "judge_answer"],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """The bounds and the random source are keyword-only, and in that order.

    `draw(system, 1, 100)` would read as three interchangeable values, and a transposed
    pair of bounds would be caught by nothing at runtime.
    """
    assert signature_shape(function) == (positional, keyword_only)


def test_invalid_range_error_is_a_value_error() -> None:
    """One family to catch: T04 turns any `ValueError` from here into a 400."""
    assert issubclass(InvalidRangeError, ValueError)


def test_verdict_has_exactly_three_outcomes() -> None:
    """Three outcomes, not a boolean with a special case: the names are the contract."""
    assert [verdict.name for verdict in Verdict] == ["CORRECT", "INCORRECT", "NOT_A_NUMBER"]
    assert [verdict.value for verdict in Verdict] == ["correct", "incorrect", "not_a_number"]


# ---------------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_a_seeded_draw_lands_in_the_range_and_renders_that_number(system: NumeralSystem) -> None:
    """The question's text is the numerals module's rendering of the drawn number.

    The expectation calls `render_number` rather than restating a Hangul string: a test
    that re-implemented the rendering would pass just as happily against a broken table.
    """
    question = draw_number_question(system, minimum=1, maximum=99, rng=seeded())

    assert 1 <= question.number <= 99
    assert question.text == render_number(question.number, system)


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_the_question_carries_the_system_it_was_drawn_with(system: NumeralSystem) -> None:
    """Otherwise a later caller has to remember it, and one day will not."""
    question = draw_number_question(system, minimum=1, maximum=99, rng=seeded())

    assert question.system is system


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_the_same_seed_draws_the_same_question(system: NumeralSystem) -> None:
    """The injected source is the only source of randomness: same seed, same question."""
    first = draw_number_question(system, minimum=1, maximum=99, rng=seeded())
    second = draw_number_question(system, minimum=1, maximum=99, rng=seeded())

    assert first == second


@pytest.mark.parametrize("field_name", ["number", "text", "system"], ids=["number", "text", "sys"])
def test_a_drawn_question_cannot_be_mutated(field_name: str) -> None:
    """T04 keeps pending questions in memory; a mutable one is a rewritable answer key."""
    question = make_question(NumeralSystem.SINO)

    assert [field.name for field in dataclasses.fields(question)] == ["number", "text", "system"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(question, field_name, 43)


@pytest.mark.parametrize(
    ("system", "minimum", "maximum"),
    [(NumeralSystem.SINO, 1, 100), (NumeralSystem.NATIVE, 1, 99)],
    ids=["sino-1-100", "native-1-99"],
)
def test_two_hundred_real_draws_stay_inside_the_requested_range(
    system: NumeralSystem, minimum: int, maximum: int
) -> None:
    """A real, unseeded source: every draw in range, and the sample spans most of it.

    In-range is the hard invariant and is asserted exactly. The spread is deliberately
    loose (the sample must reach within 9 of each bound, which a uniform draw misses
    about once in a billion runs) rather than demanding the exact bounds, which 200 draws
    over 100 values miss roughly a quarter of the time.
    """
    source = random.Random()
    numbers_drawn = [
        draw_number_question(system, minimum=minimum, maximum=maximum, rng=source).number
        for _ in range(SAMPLE_SIZE)
    ]

    assert min(numbers_drawn) >= minimum
    assert max(numbers_drawn) <= maximum
    assert min(numbers_drawn) <= minimum + 9
    assert max(numbers_drawn) >= maximum - 9


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_both_bounds_of_a_range_are_reachable(system: NumeralSystem) -> None:
    """Neither bound is quietly excluded: over two values, 100 draws must find both.

    A range of two makes "both bounds reachable" a certainty rather than a coin flip: an
    off-by-one that excluded either bound would produce a one-element set every time.
    """
    source = random.Random()
    drawn = {
        draw_number_question(system, minimum=1, maximum=2, rng=source).number for _ in range(100)
    }

    assert drawn == {1, 2}


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_omitting_the_range_draws_from_the_systems_full_supported_range(
    system: NumeralSystem,
) -> None:
    """No range given means exactly "the whole supported range", not a hidden default.

    Asserted by equality against the explicit request under the same seed, so the test
    never restates the bounds and keeps holding if the Sino ceiling is raised later.
    """
    span = supported_range(system)
    implicit = draw_number_question(system, rng=seeded())
    explicit = draw_number_question(
        system, minimum=span.minimum, maximum=span.maximum, rng=seeded()
    )

    assert implicit == explicit
    assert span.minimum <= implicit.number <= span.maximum
    assert implicit.text == render_number(implicit.number, system)


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_omitting_rng_falls_back_to_a_real_random_source(system: NumeralSystem) -> None:
    """The one call in this file that leaves `rng` out entirely.

    Every other test above injects a `random.Random`, seeded or not, which is exactly
    what keeps them deterministic or at least reproducible - but it also means the
    `random.Random() if rng is None else rng` fallback inside `draw_number_question` has
    never run. Leaving the argument out is the only way to reach it.
    """
    question = draw_number_question(system)

    span = supported_range(system)
    assert span.minimum <= question.number <= span.maximum
    assert question.text == render_number(question.number, system)


@pytest.mark.parametrize(
    ("system", "minimum", "maximum"),
    [
        (NumeralSystem.SINO, 7, None),
        (NumeralSystem.SINO, None, 7),
        (NumeralSystem.NATIVE, 7, None),
        (NumeralSystem.NATIVE, None, 7),
    ],
    ids=["sino-minimum-only", "sino-maximum-only", "native-minimum-only", "native-maximum-only"],
)
def test_one_bound_alone_falls_back_to_the_supported_one_for_the_other(
    system: NumeralSystem, minimum: int | None, maximum: int | None
) -> None:
    """Half a range is still a valid request: the missing half is the system's own.

    Beyond the ticket, which only specifies both bounds or neither. Left undefined, the
    natural half-open request is where a silent clamp or a `TypeError` would appear. An
    explicit `None` has to mean the same as leaving the argument out, since that is what
    an HTTP layer with two optional query parameters will hand over.
    """
    span = supported_range(system)
    question = draw_number_question(system, minimum=minimum, maximum=maximum, rng=seeded())

    expected_minimum = span.minimum if minimum is None else minimum
    expected_maximum = span.maximum if maximum is None else maximum
    assert expected_minimum <= question.number <= expected_maximum


def test_native_draws_never_reach_one_hundred() -> None:
    """The ceiling is the whole point of the second system, over its own default range."""
    source = random.Random()
    numbers_drawn = [
        draw_number_question(NumeralSystem.NATIVE, rng=source).number for _ in range(SAMPLE_SIZE)
    ]

    assert 100 not in numbers_drawn
    assert max(numbers_drawn) <= 99
    assert min(numbers_drawn) >= 1


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_a_minimum_above_its_maximum_is_rejected(system: NumeralSystem) -> None:
    """An empty range is a caller mistake, not an empty draw or a silent swap."""
    with pytest.raises(InvalidRangeError):
        draw_number_question(system, minimum=10, maximum=5, rng=seeded())


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_a_single_value_range_always_draws_that_value(system: NumeralSystem) -> None:
    """5 to 5 is a legal request, and it is 5 every time, in both systems."""
    source = random.Random()
    questions = [
        draw_number_question(system, minimum=5, maximum=5, rng=source) for _ in range(20)
    ]

    assert {question.number for question in questions} == {5}
    assert {question.text for question in questions} == {render_number(5, system)}


def test_one_to_a_hundred_is_rejected_under_native_korean() -> None:
    """The pair this ticket exists for, half one: native Korean stops at 99.

    Not clamped to 99, not drawn and then rendered as something no Korean would say. The
    message names the system and its range because that is what the caller has to fix.
    """
    with pytest.raises(InvalidRangeError) as excinfo:
        draw_number_question(NumeralSystem.NATIVE, minimum=1, maximum=100, rng=seeded())

    message = str(excinfo.value).lower()
    assert "native" in message
    assert "1" in message
    assert "99" in message


def test_one_to_a_hundred_is_accepted_under_sino_korean() -> None:
    """The pair this ticket exists for, half two: same request, different verdict."""
    question = draw_number_question(NumeralSystem.SINO, minimum=1, maximum=100, rng=seeded())

    assert 1 <= question.number <= 100
    assert question.system is NumeralSystem.SINO
    assert question.text == render_number(question.number, NumeralSystem.SINO)


def test_zero_to_ten_is_rejected_under_native_korean() -> None:
    """Native Korean has no zero, so a range that includes it is not a native range."""
    with pytest.raises(InvalidRangeError) as excinfo:
        draw_number_question(NumeralSystem.NATIVE, minimum=0, maximum=10, rng=seeded())

    message = str(excinfo.value).lower()
    assert "native" in message
    assert "99" in message


def test_zero_to_ten_is_accepted_under_sino_korean() -> None:
    """영 is a real Sino-Korean word, so 0 is a legitimate question there."""
    question = draw_number_question(NumeralSystem.SINO, minimum=0, maximum=10, rng=seeded())

    assert 0 <= question.number <= 10
    assert question.text == render_number(question.number, NumeralSystem.SINO)


@pytest.mark.parametrize(
    ("system", "minimum", "maximum"),
    [
        (NumeralSystem.SINO, 1, 1000),
        (NumeralSystem.SINO, -5, 10),
        (NumeralSystem.NATIVE, 1, 200),
        (NumeralSystem.NATIVE, -1, 50),
    ],
    ids=["sino-above", "sino-below", "native-above", "native-below"],
)
def test_a_bound_outside_the_supported_range_is_rejected(
    system: NumeralSystem, minimum: int, maximum: int
) -> None:
    """The exercise range is validated against the active system, both ends of it."""
    with pytest.raises(InvalidRangeError):
        draw_number_question(system, minimum=minimum, maximum=maximum, rng=seeded())


def test_an_unknown_system_cannot_be_drawn_from() -> None:
    """No fallback to Sino-Korean here either.

    `ValueError` rather than a specific type: whether this surfaces as the numerals
    module's `NumeralError` or as `InvalidRangeError` is the implementation's call, and
    both are `ValueError`s so one `except` covers it at the HTTP boundary.
    """
    with pytest.raises(ValueError):
        draw_number_question(cast(NumeralSystem, "martian"), minimum=1, maximum=10, rng=seeded())


# ---------------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
@pytest.mark.parametrize(
    "answer",
    ["42", "  42  ", "042", "\t42\n", "0042"],
    ids=["plain", "surrounding-spaces", "one-leading-zero", "tab-and-newline", "two-leading-zeros"],
)
def test_answers_that_are_the_drawn_number_are_correct(answer: str, system: NumeralSystem) -> None:
    """Trimmed whitespace and leading zeros are the same number, in both systems."""
    result = judge(system, answer)

    assert result.verdict is Verdict.CORRECT
    assert result.expected_number == ANSWER_NUMBER
    assert result.text == render_number(ANSWER_NUMBER, system)


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
@pytest.mark.parametrize(
    "answer",
    ["43", "4", "24", "0", "420", "999999999999"],
    ids=["off-by-one", "truncated", "transposed", "zero", "extra-digit", "absurdly-large"],
)
def test_answers_that_are_a_different_number_are_incorrect(
    answer: str, system: NumeralSystem
) -> None:
    """Wrong is wrong: no partial credit for a prefix, no special case for a big number.

    "999999999999" is INCORRECT rather than not-a-number on purpose - it is a number, it
    is simply not this one, and rejecting it as unparseable would tell the user the wrong
    thing about what they typed.
    """
    result = judge(system, answer)

    assert result.verdict is Verdict.INCORRECT
    assert result.expected_number == ANSWER_NUMBER
    assert result.text == render_number(ANSWER_NUMBER, system)


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
@pytest.mark.parametrize(
    "answer",
    ["", "   ", "\t\n", "4 2", "quarante-deux", "사십이", "마흔둘", "42.0", "4_2", "42개"],
    ids=[
        "empty",
        "only-spaces",
        "only-control-whitespace",
        "internal-space",
        "french-words",
        "sino-hangul",
        "native-hangul",
        "decimal-point",
        "underscore-separator",
        "digits-with-a-counter",
    ],
)
def test_answers_that_are_not_a_number_are_reported_as_such(
    answer: str, system: NumeralSystem
) -> None:
    """Nothing typed, or something that is not digits, is not a wrong answer.

    Two of these are the reason the parse cannot be a bare `int()`: `int("4_2")` is 42 in
    Python, so a typo would be scored correct, and the Hangul cases must stay rejected in
    both systems (typing the Korean is not an accepted answer format for this exercise -
    if it should be, change the ticket, not this test).

    The result still carries the expected number and the spoken text, so the caller shows
    the same feedback whichever way the answer was wrong.
    """
    result = judge(system, answer)

    assert result.verdict is Verdict.NOT_A_NUMBER
    assert result.expected_number == ANSWER_NUMBER
    assert result.text == render_number(ANSWER_NUMBER, system)


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_a_negative_answer_is_never_correct(system: NumeralSystem) -> None:
    """A minus sign may read as unparseable or as the wrong number, never as the right one.

    The ticket leaves the choice open, so the test constrains only what matters: the sign
    must not be dropped on the way to a comparison with 42.
    """
    result = judge(system, "-42")

    # The "never correct" check comes first on purpose: after the membership assertion
    # mypy has already narrowed the verdict to the other two members, and then reports the
    # identity check it cannot see failing as a non-overlapping comparison.
    assert result.verdict is not Verdict.CORRECT
    assert result.verdict in {Verdict.NOT_A_NUMBER, Verdict.INCORRECT}


@pytest.mark.parametrize("system", SYSTEMS, ids=SYSTEM_IDS)
def test_the_same_answer_judges_the_same_in_both_systems(system: NumeralSystem) -> None:
    """Answers are digits either way, so the system decides what is spoken, not what is right."""
    assert judge(system, "42").verdict is Verdict.CORRECT
    assert judge(system, "43").verdict is Verdict.INCORRECT


@pytest.mark.parametrize(
    ("system", "spoken"),
    [(NumeralSystem.SINO, "사십이"), (NumeralSystem.NATIVE, "마흔둘")],
    ids=["sino", "native"],
)
def test_a_wrong_answer_reports_the_text_that_was_spoken(
    system: NumeralSystem, spoken: str
) -> None:
    """After a miss the caller can show what was actually said, in the right system.

    The two strings are named by the ticket itself, so they are stated literally here: a
    result that carried the Sino text for a native question would pass a
    `render_number`-derived assertion in the wrong system just as happily.
    """
    result = judge(system, "43")

    assert result.verdict is Verdict.INCORRECT
    assert result.expected_number == ANSWER_NUMBER
    assert result.text == spoken


def test_judging_the_same_answer_twice_gives_the_same_result() -> None:
    """No hidden state: no attempt counter, no consumed question, no mutated answer key."""
    question = make_question(NumeralSystem.NATIVE)

    first = judge_answer(question, "43")
    second = judge_answer(question, "43")

    assert first == second
    assert question.number == ANSWER_NUMBER
    assert question.text == render_number(ANSWER_NUMBER, NumeralSystem.NATIVE)


@pytest.mark.parametrize(
    "field_name", ["verdict", "expected_number", "text"], ids=["verdict", "number", "text"]
)
def test_a_judgement_cannot_be_mutated(field_name: str) -> None:
    """The verdict is a result, not a scratchpad a caller can edit on its way out."""
    result = judge(NumeralSystem.SINO, "43")

    assert [field.name for field in dataclasses.fields(result)] == [
        "verdict",
        "expected_number",
        "text",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(result, field_name, "tampered")
