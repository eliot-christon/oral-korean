"""Tests for refusing a typed vocabulary answer in the wrong script: vocab-answer-script-check.

Written before the implementation, from the ticket's acceptance criteria and the decisions
settled with it. The rest of judging is pinned in `tests/test_exercises_vocab.py`; this file
is apart from it only for pylint's module length.

A typed answer in the other script is refused, not judged: `judge_answer` raises
`MalformedAnswerError`, which the route turns into a `422` that leaves the question pending and
unscored. The rule:

- **Hangul side** (translation to Hangul, voice to Hangul): refused unless the text holds a
  precomposed syllable (`hangul.contains_hangul`). Message exactly "Type your answer in Hangul."
- **Translation side** (Hangul to translation, voice to translation): refused when the text holds
  any Hangul, syllables and jamo alike (`hangul.contains_any_hangul`), unless one of the word's
  own translations holds Hangul. Message exactly "Type your answer in Latin letters."
- A blank answer is never refused: it stays a wrong answer, on both sides. Multiple choice and
  "I don't know" are unchanged.

The messages are compared whole, so neither can carry the word's Korean or translations.
Characters that are invisible or easy to mistake for another (lone and halfwidth jamo, the
ideographic space) are built with `chr()` from their code point, never typed as literals.

Pure calls throughout: no file, no patching, no clock, no HTTP. Every memory state comes from
`srs/` with fuzzing off, and every random source is seeded.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from conftest import nfd

from oral_korean.exercises.vocab import (
    AnswerMode,
    ChoiceAnswer,
    Direction,
    DontKnowAnswer,
    MalformedAnswerError,
    SubmittedAnswer,
    TypedAnswer,
    VocabQuestion,
    build_question,
    grade_for,
    judge_answer,
)
from oral_korean.exercises.vocab_words import VocabularyWord, same_memory
from oral_korean.srs.memory import Familiarity, Grade, seed

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)

HANGUL_ONLY = "Type your answer in Hangul."
LATIN_ONLY = "Type your answer in Latin letters."

DIRECTIONS = list(Direction)
DIRECTION_IDS = [direction.value for direction in DIRECTIONS]
TO_HANGUL = [Direction.TRANSLATION_TO_HANGUL, Direction.VOICE_TO_HANGUL]
TO_HANGUL_IDS = [direction.value for direction in TO_HANGUL]
TO_TRANSLATION = [Direction.HANGUL_TO_TRANSLATION, Direction.VOICE_TO_TRANSLATION]
TO_TRANSLATION_IDS = [direction.value for direction in TO_TRANSLATION]

LONE_KIYEOK = chr(0x1100)
"""A conjoining initial with no vowel: Hangul, but no syllable."""
LONE_MIEUM = chr(0x1106)
HALFWIDTH_KIYEOK = chr(0xFFA1)
HALFWIDTH_MIEUM = chr(0xFFB1)
EXTENDED_A_JAMO = chr(0xA960)
EXTENDED_B_JAMO = chr(0xD7B0)
IDEOGRAPHIC_SPACE = chr(0x3000)


def known_word(korean: str, *translations: str) -> VocabularyWord:
    """A word seeded `well` in every direction, over the typing threshold: always typed."""
    seeded = seed(Familiarity.WELL, T0, fuzzing=False)
    assert seeded is not None
    return VocabularyWord(
        20, korean, translations, (), Familiarity.WELL, T0, same_memory(seeded[0])
    )


def new_word(word_id: int, korean: str, translation: str) -> VocabularyWord:
    """A word with no memory in any direction: asked by multiple choice when it can be."""
    return VocabularyWord(
        word_id, korean, (translation,), (), Familiarity.NEW, T0, same_memory(None)
    )


def typed_in(word: VocabularyWord, direction: Direction) -> VocabQuestion:
    """A typed question for `word` in `direction`, checked to really be typed."""
    question = build_question(word, direction, rng=random.Random(0))
    assert question.mode is AnswerMode.TYPING, question
    return question


def is_right(question: VocabQuestion, answer: SubmittedAnswer) -> bool:
    return bool(judge_answer(question, answer).correct)


# ---------------------------------------------------------------------------------
# The Hangul side
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("direction", TO_HANGUL, ids=TO_HANGUL_IDS)
@pytest.mark.parametrize(
    ("korean", "translation", "answer"),
    [
        pytest.param("사과", "apple", "apple", id="the-translation-instead"),
        pytest.param("물", "water", "water", id="another-latin-word"),
        pytest.param("사과", "apple", "ㅅㅏㄱㅘ", id="compatibility-jamo-only"),
        pytest.param("사과", "apple", "ㅁㄹ", id="two-compatibility-jamo"),
        pytest.param("사과", "apple", LONE_KIYEOK, id="a-lone-conjoining-initial"),
        pytest.param("사과", "apple", HALFWIDTH_KIYEOK, id="halfwidth-jamo"),
        pytest.param("사과", "apple", "...", id="punctuation-only"),
        pytest.param("사과", "apple", "3", id="a-digit"),
        pytest.param("사과", "apple", "вода", id="cyrillic"),
        pytest.param("하다 (do)", "to do", "do", id="only-the-latin-parentheses"),
    ],
)
def test_a_typed_hangul_answer_with_no_syllable_is_refused(
    direction: Direction, korean: str, translation: str, answer: str
) -> None:
    """English typed where Korean was asked is a keyboard left in the wrong layout, not a
    lapse: refused with a fixed message that names the script and nothing of the word."""
    question = typed_in(known_word(korean, translation), direction)

    with pytest.raises(MalformedAnswerError) as refused:
        judge_answer(question, TypedAnswer(answer))

    assert str(refused.value) == HANGUL_ONLY


@pytest.mark.parametrize("direction", TO_HANGUL, ids=TO_HANGUL_IDS)
@pytest.mark.parametrize(
    ("korean", "translation", "answer", "right"),
    [
        pytest.param("T셔츠", "T-shirt", "T셔츠", True, id="latin-inside-the-word"),
        pytest.param("T셔츠", "T-shirt", "t셔츠", True, id="latin-inside-the-word-lowercase"),
        pytest.param("T셔츠", "T-shirt", "셔츠", False, id="latin-part-left-out"),
        pytest.param("물", "water", "물 water", False, id="hangul-and-latin-mixed"),
        pytest.param("물", "water", nfd("물", 3), True, id="decomposed-syllable"),
        pytest.param("물", "water", "물ㅁ", False, id="syllable-and-a-stray-jamo"),
        pytest.param("물", "water", "불", False, id="another-hangul-word"),
    ],
)
def test_a_typed_hangul_answer_holding_a_syllable_is_judged(
    direction: Direction, korean: str, translation: str, answer: str, right: bool
) -> None:
    """One syllable is enough to be judged: Latin letters beside Hangul are part of some words
    (T셔츠), a decomposed syllable is still a syllable, and a mix is simply right or wrong."""
    question = typed_in(known_word(korean, translation), direction)

    assert is_right(question, TypedAnswer(answer)) is right


# ---------------------------------------------------------------------------------
# The translation side
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("direction", TO_TRANSLATION, ids=TO_TRANSLATION_IDS)
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("물", id="the-korean-instead"),
        pytest.param("불", id="another-hangul-word"),
        pytest.param("ㅁ", id="a-compatibility-jamo"),
        pytest.param("water ㅁ", id="the-right-answer-and-a-stray-jamo"),
        pytest.param("water 물", id="latin-and-hangul-mixed"),
        pytest.param(nfd("물", 3), id="decomposed-syllable"),
        pytest.param(LONE_MIEUM, id="a-lone-conjoining-initial"),
        pytest.param(HALFWIDTH_MIEUM, id="halfwidth-jamo"),
        pytest.param(EXTENDED_A_JAMO, id="extended-a-jamo"),
        pytest.param(EXTENDED_B_JAMO, id="extended-b-jamo"),
    ],
)
def test_a_typed_translation_holding_any_hangul_is_refused(
    direction: Direction, answer: str
) -> None:
    """A Korean keyboard left on types jamo as well as syllables, so any Hangul at all is
    refused, a right translation beside it included."""
    question = typed_in(known_word("물", "water"), direction)

    with pytest.raises(MalformedAnswerError) as refused:
        judge_answer(question, TypedAnswer(answer))

    assert str(refused.value) == LATIN_ONLY


@pytest.mark.parametrize("direction", TO_TRANSLATION, ids=TO_TRANSLATION_IDS)
@pytest.mark.parametrize(
    ("translations", "answer", "right"),
    [
        pytest.param(("water", "eau"), "eau", True, id="french"),
        pytest.param(("café",), "café", True, id="accented-latin"),
        pytest.param(("café",), nfd("café", 5), True, id="accented-latin-decomposed"),
        pytest.param(("three",), "3", False, id="a-digit"),
        pytest.param(("3",), "3", True, id="a-digit-translation"),
        pytest.param(("rat", "mouse"), "rat, mouse", True, id="two-translations"),
        pytest.param(("water",), "вода", False, id="cyrillic-is-judged"),
        pytest.param(("water",), "水", False, id="hanja-is-judged"),
        pytest.param(("water",), "...", False, id="punctuation-only"),
    ],
)
def test_a_typed_translation_with_no_hangul_is_judged(
    direction: Direction, translations: tuple[str, ...], answer: str, right: bool
) -> None:
    """No "Latin letters only" check: digits, punctuation, accents and other scripts are
    judged as they always were, so a translation like "3" stays answerable."""
    question = typed_in(known_word("물", *translations), direction)

    assert is_right(question, TypedAnswer(answer)) is right


@pytest.mark.parametrize("direction", TO_TRANSLATION, ids=TO_TRANSLATION_IDS)
@pytest.mark.parametrize(
    ("translations", "answer", "right"),
    [
        pytest.param(("kimchi (김치)",), "kimchi (김치)", True, id="as-stored"),
        pytest.param(("kimchi (김치)",), "kimchi", True, id="parentheses-left-out"),
        pytest.param(("kimchi (김치)",), "김치", False, id="only-the-hangul-part"),
        pytest.param(("kimchi (김치)",), "ㄱ", False, id="a-jamo"),
        pytest.param(("coffee", "커피"), "커피", True, id="one-translation-all-hangul"),
        pytest.param(("coffee", "커피"), "coffee", True, id="the-latin-one"),
    ],
)
def test_a_word_whose_translation_holds_hangul_is_judged_whatever_the_script(
    direction: Direction, translations: tuple[str, ...], answer: str, right: bool
) -> None:
    """Storage accepts Hangul in a translation; refusing Hangul then would leave such a word
    with no answer that can ever be right, so the check steps aside for it."""
    question = typed_in(known_word("김치", *translations), direction)

    assert is_right(question, TypedAnswer(answer)) is right


# ---------------------------------------------------------------------------------
# What does not change
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="spaces"),
        pytest.param(IDEOGRAPHIC_SPACE, id="ideographic-space"),
    ],
)
def test_a_blank_typed_answer_is_wrong_not_refused_in_every_direction(
    direction: Direction, answer: str
) -> None:
    """Blank is in neither script, and it is a miss as it always was: refusing it would let a
    user skip a hard word without the `again` it earns."""
    question = typed_in(known_word("물", "water"), direction)

    judgement = judge_answer(question, TypedAnswer(answer))

    assert judgement.correct is False
    assert grade_for(correct=judgement.correct, mode=question.mode) is Grade.AGAIN


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_i_dont_know_on_a_typed_question_is_never_refused_for_its_script(
    direction: Direction,
) -> None:
    """"I don't know" carries no text, so the script check never reaches it."""
    question = typed_in(known_word("물", "water"), direction)

    assert is_right(question, DontKnowAnswer()) is False


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_a_tapped_question_is_judged_whatever_the_script_of_its_options(
    direction: Direction,
) -> None:
    """Multiple choice sends an index, never text: every option stays tappable in every
    direction, the right one right and the others wrong."""
    candidates = [
        new_word(2, "불", "fire"),
        new_word(3, "사과", "apple"),
        new_word(4, "책", "book"),
    ]
    question = build_question(
        new_word(1, "물", "water"), direction, candidates=candidates, rng=random.Random(0)
    )
    assert question.mode is AnswerMode.CHOICE
    assert question.correct_index is not None

    verdicts = [is_right(question, ChoiceAnswer(index)) for index in range(len(question.options))]

    assert verdicts.count(True) == 1
    assert verdicts[question.correct_index] is True
