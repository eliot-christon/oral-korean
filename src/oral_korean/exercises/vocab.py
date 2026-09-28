"""The vocabulary exercise: which directions, which mode, what counts as right, what grade.

Pure, like `exercises/numbers.py`: no HTTP, no storage, no audio. This module chooses the
directions a word is asked in during a session, from each direction's own memory; given a
word, its candidates and a random source, it builds a question in one direction, in the mode
that direction's FSRS state calls for, judges a submitted answer, and maps the outcome onto
an FSRS grade. `vocab_session.py` sequences a learn or review session over the words and
their directions; its names are re-exported here so one import covers both.

**The grade mapping is the one place a mistake here is silent**: a right answer scored as
a lapse raises nothing, the word just comes back at the wrong interval. Multiple choice
grades `hard`, typing grades `good`, so typing weighs more - and only because `srs/`
disables FSRS's learning steps, without which a `hard` grade never leaves the first
learning step and a word answered by multiple choice never reaches typing at all.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from oral_korean.exercises.vocab_session import (
    DirectionResult,
    ItemKind,
    SessionItem,
    SessionKind,
    SessionPlan,
    SessionProgress,
    SessionStateError,
    SessionSummary,
    WordResult,
)
from oral_korean.exercises.vocab_words import Direction, VocabularyWord, split_translations
from oral_korean.korean import hangul
from oral_korean.srs.memory import Grade, MemoryState

__all__ = [
    "TYPING_STABILITY_DAYS",
    "AnswerMode",
    "ChoiceAnswer",
    "Choices",
    "Direction",
    "DirectionResult",
    "DontKnowAnswer",
    "ItemKind",
    "MalformedAnswerError",
    "SessionItem",
    "SessionKind",
    "SessionPlan",
    "SessionProgress",
    "SessionStateError",
    "SessionSummary",
    "SubmittedAnswer",
    "TypedAnswer",
    "VocabJudgement",
    "VocabQuestion",
    "WordResult",
    "answer_mode",
    "build_question",
    "directions_to_ask",
    "grade_for",
    "judge_answer",
]


class AnswerMode(StrEnum):
    """Tapped or typed - Memrise-style: multiple choice while a word is weak, typing once
    it is stronger, because typing is harder and should weigh more in the grade."""

    CHOICE = "choice"
    TYPING = "typing"


TYPING_STABILITY_DAYS: Final = 2.0
"""The stability at and above which a word is asked by typing rather than tapped.

Sits between the `a_little` (1.29 days) and `well` (2.31 days) seeds, so "a little" starts
in multiple choice and "well" starts typing, and a perfect learner types from the third
answer (see the simulation in the epic)."""

_AnswerSide = Literal["translation", "hangul"]

_MAX_DISTRACTORS: Final = 3
_TRANSLATION_JOIN: Final = ", "
_SPACING_PUNCTUATION: Final = "-/_"
_PARENTHESISED: Final = re.compile(r"\([^()]*\)")


@dataclass(frozen=True)
class Choices:
    """A multiple-choice question's options, shuffled, and which of them is right.

    Attributes:
        options: the texts offered, pairwise distinct.
        correct_index: the position of the right one in `options`.
    """

    options: tuple[str, ...]
    correct_index: int


@dataclass(frozen=True)
class VocabQuestion:
    """One built question: the answer key, kept server-side by T03.

    Attributes:
        word: the word asked about, as it was when the question was built - a word
            edited or deleted mid-session is judged against this snapshot.
        direction: which side is shown or spoken, and which side answers it.
        prompt: the written text shown, or `None` for a voice direction.
        speech: the Korean to speak, or `None` for a written direction.
        choices: the options and the right one, or `None` for typing - which is what
            `mode` reports, so the mode actually used can never disagree with the key.
        accepted_answers: every typed answer that counts as right; empty for multiple
            choice.
    """

    word: VocabularyWord
    direction: Direction
    prompt: str | None
    speech: str | None
    choices: Choices | None
    accepted_answers: tuple[str, ...]

    @property
    def mode(self) -> AnswerMode:
        """The mode actually used - `build_question` falls back to typing even when the
        word's own state calls for multiple choice, if no distractor is eligible."""
        return AnswerMode.TYPING if self.choices is None else AnswerMode.CHOICE

    @property
    def word_id(self) -> int:
        return self.word.id

    @property
    def korean(self) -> str:
        return self.word.korean

    @property
    def translations(self) -> tuple[str, ...]:
        return self.word.translations

    @property
    def options(self) -> tuple[str, ...]:
        """The multiple-choice options; empty for typing."""
        return () if self.choices is None else self.choices.options

    @property
    def correct_index(self) -> int | None:
        """Which option is right; `None` for typing."""
        return None if self.choices is None else self.choices.correct_index


@dataclass(frozen=True)
class VocabJudgement:
    """The verdict on one answer, with everything the feedback card shows.

    Attributes:
        correct: whether the answer was right.
        korean: the word's Korean, shown whichever way the answer went.
        translations: the word's translations, shown whichever way the answer went.
        correct_option: the text of the right option, for multiple choice; `None` for
            typing, where the accepted answers already say what was expected.
    """

    correct: bool
    korean: str
    translations: tuple[str, ...]
    correct_option: str | None


@dataclass(frozen=True)
class TypedAnswer:
    """A typed submission, exactly as the user entered it."""

    text: str


@dataclass(frozen=True)
class ChoiceAnswer:
    """A tapped submission: the index of the option chosen."""

    index: int


@dataclass(frozen=True)
class DontKnowAnswer:
    """"I don't know", offered in both modes and always wrong."""


SubmittedAnswer = TypedAnswer | ChoiceAnswer | DontKnowAnswer


class MalformedAnswerError(ValueError):
    """A submission that does not fit the question it answers: an out-of-range or
    negative choice index, text for a multiple-choice question, or an index for a typing
    one. Distinct from a wrong answer, so a caller can refuse it without scoring the
    question or consuming it."""


def answer_mode(memory: MemoryState | None) -> AnswerMode:
    """The mode a word's own memory calls for: typing from `TYPING_STABILITY_DAYS`."""
    if memory is None or memory.stability < TYPING_STABILITY_DAYS:
        return AnswerMode.CHOICE
    return AnswerMode.TYPING


def grade_for(*, correct: bool, mode: AnswerMode) -> Grade:
    """The FSRS grade for an outcome: wrong is always `again`; right is `hard` by
    multiple choice and `good` by typing. `easy` never comes from an answer, and neither
    ever depends on the direction - `judge_answer` never even carries one."""
    if not correct:
        return Grade.AGAIN
    return Grade.HARD if mode is AnswerMode.CHOICE else Grade.GOOD


def directions_to_ask(
    word: VocabularyWord, kind: SessionKind, ticked: Collection[Direction], at: datetime
) -> tuple[Direction, ...]:
    """The directions `word` is asked in, among the `ticked` ones, in `Direction` order.

    A learn session asks every direction with no memory yet. A review session asks every
    learned direction that is due at `at`, or, when none is (a word the user chose to review
    early), every learned one. A direction never learned is never reviewed, nor a learned one
    learned again. `()` leaves the word out of the session.
    """
    wanted = [direction for direction in Direction if direction in ticked]
    if kind is SessionKind.LEARN:
        return tuple(direction for direction in wanted if word.memories[direction] is None)
    learned = {
        direction: memory
        for direction in wanted
        if (memory := word.memories[direction]) is not None
    }
    due = tuple(direction for direction, memory in learned.items() if at >= memory.next_review)
    return due or tuple(learned)


def build_question(
    word: VocabularyWord,
    direction: Direction,
    *,
    candidates: Sequence[VocabularyWord] = (),
    rng: random.Random | None = None,
) -> VocabQuestion:
    """Build a question for `word` in `direction`, in the mode that direction's memory calls
    for.

    `candidates` is the pool multiple choice draws distractors from - the whole
    vocabulary, not just the word's own tag. With no eligible distractor the question
    falls back to typing, and `mode` reports the mode actually used.
    """
    source = rng if rng is not None else random.Random()
    side = _answer_side(direction)

    if answer_mode(word.memories[direction]) is AnswerMode.CHOICE:
        choice_question = _build_choice_question(word, direction, side, candidates, source)
        if choice_question is not None:
            return choice_question

    prompt, speech = _prompt_and_speech(word, direction)
    accepted = word.translations if side == "translation" else (word.korean,)
    return VocabQuestion(
        word=word,
        direction=direction,
        prompt=prompt,
        speech=speech,
        choices=None,
        accepted_answers=tuple(accepted),
    )


def judge_answer(question: VocabQuestion, answer: SubmittedAnswer) -> VocabJudgement:
    """Judge `answer` against `question`. Pure: `question` is never mutated.

    Raises:
        MalformedAnswerError: `answer` does not fit `question`'s mode.
    """
    correct = _is_correct(question, answer)
    choices = question.choices
    correct_option = None if choices is None else choices.options[choices.correct_index]
    return VocabJudgement(
        correct=correct,
        korean=question.korean,
        translations=question.translations,
        correct_option=correct_option,
    )


def _is_correct(question: VocabQuestion, answer: SubmittedAnswer) -> bool:
    """Whether `answer` is right for `question`, raising on one that does not fit it."""
    if isinstance(answer, DontKnowAnswer):
        return False
    if question.choices is not None:
        return _judge_choice(question.choices, answer)
    return _judge_typed(question, answer)


def _judge_choice(choices: Choices, answer: SubmittedAnswer) -> bool:
    if not isinstance(answer, ChoiceAnswer):
        raise MalformedAnswerError("A multiple-choice question needs a choice index.")
    if not 0 <= answer.index < len(choices.options):
        raise MalformedAnswerError(f"Choice index {answer.index} is out of range.")
    return answer.index == choices.correct_index


def _judge_typed(question: VocabQuestion, answer: SubmittedAnswer) -> bool:
    if not isinstance(answer, TypedAnswer):
        raise MalformedAnswerError("A typing question needs typed text.")
    if _answer_side(question.direction) == "translation":
        return _translation_matches(question.accepted_answers, answer.text)
    answer_key = hangul.match_key(answer.text)
    return bool(answer_key) and answer_key in _hangul_keys(question.accepted_answers[0])


def _answer_side(direction: Direction) -> _AnswerSide:
    """Which side of the word a question in `direction` is answered with."""
    if direction in (Direction.HANGUL_TO_TRANSLATION, Direction.VOICE_TO_TRANSLATION):
        return "translation"
    return "hangul"


def _prompt_and_speech(word: VocabularyWord, direction: Direction) -> tuple[str | None, str | None]:
    """The written prompt and the Korean to speak, per the direction table."""
    if direction is Direction.HANGUL_TO_TRANSLATION:
        return word.korean, None
    if direction is Direction.TRANSLATION_TO_HANGUL:
        return _TRANSLATION_JOIN.join(word.translations), None
    return None, word.korean  # VOICE_TO_HANGUL and VOICE_TO_TRANSLATION


def _option_text(word: VocabularyWord, side: _AnswerSide) -> str:
    """The text one word contributes to a multiple-choice list, on `side`."""
    if side == "translation":
        return _TRANSLATION_JOIN.join(word.translations)
    return word.korean


def _build_choice_question(
    word: VocabularyWord,
    direction: Direction,
    side: _AnswerSide,
    candidates: Sequence[VocabularyWord],
    source: random.Random,
) -> VocabQuestion | None:
    """A multiple-choice question for `word`, or `None` if no distractor is eligible."""
    correct_text = _option_text(word, side)
    distractors = _eligible_distractors(word, side, candidates)
    if not distractors:
        return None

    chosen = source.sample(distractors, min(_MAX_DISTRACTORS, len(distractors)))
    options = [correct_text, *(_option_text(candidate, side) for candidate in chosen)]
    source.shuffle(options)
    prompt, speech = _prompt_and_speech(word, direction)

    return VocabQuestion(
        word=word,
        direction=direction,
        prompt=prompt,
        speech=speech,
        choices=Choices(options=tuple(options), correct_index=options.index(correct_text)),
        accepted_answers=(),
    )


def _eligible_distractors(
    word: VocabularyWord,
    side: _AnswerSide,
    candidates: Sequence[VocabularyWord],
) -> list[VocabularyWord]:
    """`candidates` that may be offered against `word`: not the target, not a candidate
    that could also be a right answer, and pairwise distinct from each other on `side` -
    two options with the same text would make one of them wrong for no visible reason."""
    seen_keys = {_option_key(word, side)}
    eligible = []
    for candidate in candidates:
        if not _could_never_be_right(word, candidate):
            continue
        key = _option_key(candidate, side)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        eligible.append(candidate)
    return eligible


def _option_key(word: VocabularyWord, side: _AnswerSide) -> str:
    """What two options are compared by, the way their side is judged: `water` and
    `Water!` would look like the same button, as would two spellings of one Hangul key."""
    if side == "translation":
        return _TRANSLATION_JOIN.join(_normalise_translation(t) for t in word.translations)
    return hangul.match_key(word.korean)


def _could_never_be_right(target: VocabularyWord, candidate: VocabularyWord) -> bool:
    """Whether `candidate` is safe to offer against `target`: not the same word (by id or
    Hangul match key) and sharing none of `target`'s translations, in either direction -
    each of those could make tapping `candidate` a right answer marked wrong."""
    if candidate.id == target.id:
        return False
    if hangul.match_key(candidate.korean) == hangul.match_key(target.korean):
        return False
    return _translation_keys(target.translations).isdisjoint(
        _translation_keys(candidate.translations)
    )


def _translation_matches(accepted: Sequence[str], answer: str) -> bool:
    """Whether every translation in `answer` matches one of `accepted`, once normalised.

    The answer is split like a word's translations, so `rat` and `rat, mouse` are both right
    for `rat, mouse`. Each part may keep or drop what the accepted translation has in
    parentheses: `fun` and `fun (short form)` are both right for `fun (short form)`. A part
    with nothing left after normalisation makes the answer wrong even against a translation
    that normalises to nothing too (`...` is a translation storage accepts): a blank answer
    must never grade `good`.
    """
    parts = [_normalise_translation(part) for part in split_translations(answer)]
    if not parts or not all(parts):
        return False
    keys = _translation_keys(accepted)
    return all(part in keys for part in parts)


def _translation_keys(translations: Sequence[str]) -> set[str]:
    """Every normalised form a typed part may take to match one of `translations`: each in
    full, and each without its parenthesised parts. Never the empty key."""
    keys = {
        _normalise_translation(form)
        for translation in translations
        for form in (translation, _without_parentheses(translation))
    }
    return keys - {""}


def _hangul_keys(korean: str) -> set[str]:
    """The Hangul match keys a typed answer may have for `korean`: in full, and without its
    parenthesised parts. Never the empty key."""
    return {hangul.match_key(korean), hangul.match_key(_without_parentheses(korean))} - {""}


def _without_parentheses(text: str) -> str:
    """`text` with every parenthesised part removed, innermost first: `fun (short form)` is
    `fun `."""
    while True:
        stripped = _PARENTHESISED.sub(" ", text)
        if stripped == text:
            return text
        text = stripped


def _normalise_translation(text: str) -> str:
    """`text` as the key two typed translations are compared by.

    Accents dropped (NFKD, combining marks stripped), casefolded, hyphens/slashes/
    underscores turned into spaces (so they behave like word breaks rather than being
    silently deleted), every other punctuation character removed, whitespace collapsed.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    folded = without_marks.casefold()
    spaced = "".join(" " if char in _SPACING_PUNCTUATION else char for char in folded)
    without_punctuation = "".join(
        char for char in spaced if not unicodedata.category(char).startswith("P")
    )
    return " ".join(without_punctuation.split())
