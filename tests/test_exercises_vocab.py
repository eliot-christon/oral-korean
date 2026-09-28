"""Tests for the vocabulary exercise: directions, modes, grading, building and judging.

Written from vocab-sessions T02's acceptance criteria and test contract, before the
implementation, and they define the contract it satisfies. The session plan has its own file,
`tests/test_exercises_vocab_session.py`; everything is imported from
`oral_korean.exercises.vocab`, so a `vocab_session.py` split must be re-exported from there.

- `Direction` (`StrEnum`): `HANGUL_TO_TRANSLATION`, `TRANSLATION_TO_HANGUL`, `VOICE_TO_HANGUL`,
  `VOICE_TO_TRANSLATION`, valued as the wire names T03 takes off a request.
- `AnswerMode` (`StrEnum`): `CHOICE` ("choice"), `TYPING` ("typing").
- `TYPING_STABILITY_DAYS = 2.0`, the named threshold.
- `VocabQuestion` (frozen): `word_id`, `direction`, `mode`, `prompt`, `speech`, `options`,
  `correct_index`, `accepted_answers` (some of them read-only properties over its fields) -
  the answer key T03 keeps server-side.
- `VocabJudgement` (frozen): `correct`, `korean`, `translations`, `correct_option`.
- `TypedAnswer(text)`, `ChoiceAnswer(index)`, `DontKnowAnswer()` and the union `SubmittedAnswer`;
  `MalformedAnswerError(ValueError)` refuses an unusable submission.
- `answer_mode(memory)`, `grade_for(*, correct, mode)`,
  `build_question(word, direction, *, candidates=(), rng=None)`, `judge_answer(question, answer)`.

`draw_direction` went with vocab-directions T02: a session now asks each word in the directions
`directions_to_ask` chooses, pinned in `tests/test_exercises_vocab_session.py`.

Decisions taken here that the ticket leaves open, flagged in the hand-back report:

1. **A submission is one of three small frozen values**, not a loose `str | int | None`: `bool`
   is an `int`, so a union of primitives could not tell a choice index from a mistake.
2. **`grade_for` takes no direction**: it cannot change the grade if it never reaches the
   mapping, and the whole chain is proven direction-blind end to end instead.
3. **`build_question` decides the mode itself**, from the memory of the direction asked
   (`word.memories[direction]`, vocab-directions T01), because falling
   back to typing when no distractor is eligible is a decision only the builder can make.
4. **Distractor eligibility is direction-blind**: the target, a shared Hangul match key and a
   shared translation each disqualify a candidate in all four directions (the ticket's
   Background), even though the epic's table reads per answer side.
5. **The `; `-joined texts are the ticket's own** and are pinned as literals; no test joins a
   word's translations itself.
6. **The threshold is pinned with `dataclasses.replace` on a state `srs/` built**: no seed lands
   on 1.99 or 2.0, and hand-building a `MemoryState` would invent FSRS figures.

Pure calls throughout: no file, no patching, no clock, no HTTP. Random sources are always a
seeded `random.Random`, and every memory state comes from `srs/` with fuzzing off.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import random
import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from types import ModuleType

import pytest
from conftest import FORBIDDEN_IMPORTS, imported_module_names, signature_shape

from oral_korean.exercises.vocab import (
    TYPING_STABILITY_DAYS,
    AnswerMode,
    ChoiceAnswer,
    Direction,
    DontKnowAnswer,
    MalformedAnswerError,
    SubmittedAnswer,
    TypedAnswer,
    VocabJudgement,
    VocabQuestion,
    answer_mode,
    build_question,
    grade_for,
    judge_answer,
)
from oral_korean.exercises.vocab_words import VocabularyWord, same_memory
from oral_korean.srs.memory import Familiarity, Grade, MemoryState, apply_grade, seed

T0 = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
"""The instant every test word was added and every simulated history starts from."""

DAY = timedelta(days=1)

SEEDS = range(50)
"""Fifty seeded draws: enough that a position or a candidate that never comes up cannot hide."""

DIRECTIONS = list(Direction)
DIRECTION_IDS = [direction.value for direction in DIRECTIONS]
MODES = list(AnswerMode)
MODE_IDS = [mode.value for mode in MODES]
TO_HANGUL = [Direction.TRANSLATION_TO_HANGUL, Direction.VOICE_TO_HANGUL]
TO_HANGUL_IDS = [direction.value for direction in TO_HANGUL]


def make_word(
    word_id: int, korean: str, *translations: str, familiarity: Familiarity = Familiarity.NEW
) -> VocabularyWord:
    """One stored word, as storage hands it over; every direction's memory is `srs/`'s own
    seed, as adding a word does (vocab-directions T01)."""
    seeded = seed(familiarity, T0, fuzzing=False)
    return VocabularyWord(
        id=word_id,
        korean=korean,
        translations=translations,
        tags=(),
        familiarity=familiarity,
        added_at=T0,
        memories=same_memory(None if seeded is None else seeded[0]),
    )


# The ticket's test vocabulary, named after the Korean so no English label can be mistaken for
# another word's. 가정 shares "home" with 집 and is the candidate 집 may never be asked against.
JIP = make_word(1, "집", "house", "home")
GAJEONG = make_word(2, "가정", "home", "family")
SAGWA = make_word(3, "사과", "apple")
BAE = make_word(4, "배", "pear", "ship", "belly")
MUL = make_word(5, "물", "water")
CHAEK = make_word(6, "책", "book")

CANDIDATES = (GAJEONG, SAGWA, BAE, MUL, CHAEK)
"""The whole vocabulary but 집: four eligible distractors, so a question has four options."""

SIKSU = make_word(7, "식수", "water")
"""A second word translated "water": two candidates whose translation side is one text."""

JIP_AGAIN = make_word(8, "집!", "residence")
"""집 spelled with an exclamation mark: another string, the same match key. Storage would refuse
it, so it is built here - and its translation collides with nothing, so only the match-key rule
can keep it out of the options."""

COLLIDING_CANDIDATES = (GAJEONG, SAGWA, BAE, MUL, SIKSU, CHAEK, JIP_AGAIN)

KNOWN_JIP = make_word(1, "집", "house", "home", familiarity=Familiarity.WELL)
"""집 with the `well` seed's 2.31 days of stability: over the threshold, so it is typed."""


def memory_of(familiarity: Familiarity) -> MemoryState:
    """The state `familiarity` seeds on T0, failing loudly rather than returning `None`."""
    seeded = seed(familiarity, T0, fuzzing=False)
    assert seeded is not None, f"{familiarity} must seed a memory state"
    return seeded[0]


def with_stability(stability: float) -> MemoryState:
    """A state `srs/` built, moved to exactly `stability` days.

    The threshold is a boundary on one number and no seed lands on 1.99 or 2.0, so the edge is
    pinned by replacing that one field rather than by inventing a whole FSRS state.
    """
    return dataclasses.replace(memory_of(Familiarity.WELL), stability=stability)


def drawn(
    target: VocabularyWord,
    direction: Direction,
    *,
    candidates: Sequence[VocabularyWord] = (),
    seed_value: int = 0,
) -> VocabQuestion:
    """A question for `target`, built from a freshly seeded random source."""
    return build_question(target, direction, candidates=candidates, rng=random.Random(seed_value))


def options_across_seeds(
    direction: Direction, candidates: Sequence[VocabularyWord]
) -> list[str]:
    """Every option offered for 집 in `direction` over the fifty seeds, flattened."""
    return [
        option
        for value in SEEDS
        for option in drawn(JIP, direction, candidates=candidates, seed_value=value).options
    ]


def correct_option(question: VocabQuestion) -> str:
    """The option a multiple-choice question calls right, read through its own index."""
    assert question.mode is AnswerMode.CHOICE, question
    assert question.correct_index is not None, "a choice question always has a correct index"
    return str(question.options[question.correct_index])


def typed_question(korean: str, *translations: str) -> VocabQuestion:
    """A Hangul-to-translation typed question for a word made of `korean` and `translations`."""
    target = make_word(99, korean, *translations, familiarity=Familiarity.WELL)
    return drawn(target, Direction.HANGUL_TO_TRANSLATION)


def is_right(question: VocabQuestion, answer: SubmittedAnswer) -> bool:
    """Whether `answer` is right for `question`, dropping the rest of the judgement."""
    return bool(judge_answer(question, answer).correct)


def nfd(text: str, length: int) -> str:
    """`text` decomposed, checked to hold exactly `length` code points.

    The length is the proof it really is decomposed: a precomposed string left here by mistake
    would be shorter, and the test using it would pass for the wrong reason.
    """
    result = unicodedata.normalize("NFD", text)
    assert len(result) == length, f"{text!r} decomposes to {len(result)} code points, not {length}"
    return result


def answered_in_turn(
    start: MemoryState | None, *, correct: bool, answers: int
) -> tuple[list[AnswerMode], list[MemoryState]]:
    """Walk a word through `answers` answers, each on the due date the last one set.

    The mode comes from the rule, the grade from the mapping and the new state from `srs/`:
    this is the whole chain the liveness tests are about, with nothing re-implemented.
    """
    modes: list[AnswerMode] = []
    states: list[MemoryState] = []
    state = start
    at = T0 if start is None else start.next_review
    for _ in range(answers):
        mode = answer_mode(state)
        state, _ = apply_grade(state, grade_for(correct=correct, mode=mode), at, fuzzing=False)
        modes.append(mode)
        states.append(state)
        at = state.next_review
    return modes, states


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


def test_direction_has_exactly_four_members_with_their_wire_values() -> None:
    """The values are what a session request carries (T03), so a rename fails here first."""
    assert DIRECTION_IDS[:2] == ["hangul_to_translation", "translation_to_hangul"]
    assert DIRECTION_IDS[2:] == ["voice_to_hangul", "voice_to_translation"]
    assert [direction.name for direction in Direction] == [name.upper() for name in DIRECTION_IDS]
    assert Direction("voice_to_hangul") is Direction.VOICE_TO_HANGUL


def test_answer_mode_is_choice_or_typing() -> None:
    """Two modes only: the question is either tapped or typed."""
    assert [mode.name for mode in AnswerMode] == ["CHOICE", "TYPING"]
    assert MODE_IDS == ["choice", "typing"]
    assert AnswerMode("typing") is AnswerMode.TYPING


def test_the_typing_threshold_is_a_named_constant_of_two_days() -> None:
    """A product choice, visible by name rather than buried in a comparison."""
    assert TYPING_STABILITY_DAYS == 2.0


def test_a_malformed_answer_is_a_value_error() -> None:
    """One family to catch, as `InvalidRangeError` and `WordEntryError` already are."""
    assert issubclass(MalformedAnswerError, ValueError)


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        pytest.param(answer_mode, ["memory"], [], id="answer_mode"),
        pytest.param(grade_for, [], ["correct", "mode"], id="grade_for"),
        pytest.param(
            build_question, ["word", "direction"], ["candidates", "rng"], id="build_question"
        ),
        pytest.param(judge_answer, ["question", "answer"], [], id="judge_answer"),
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """`correct` is keyword-only: a stray positional `False` would flip an outcome and nothing
    at runtime would notice. The candidates and the random source are keyword-only too."""
    assert signature_shape(function) == (positional, keyword_only)


def test_a_question_is_a_frozen_value_with_the_agreed_fields() -> None:
    """The question is the answer key T03 keeps server-side, and a mutable key is rewritable."""
    question = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=CANDIDATES)
    agreed = [
        "word_id",
        "direction",
        "mode",
        "prompt",
        "speech",
        "options",
        "correct_index",
        "accepted_answers",
        "korean",
        "translations",
    ]
    fields = [field.name for field in dataclasses.fields(question)]

    assert isinstance(question, VocabQuestion)
    for name in agreed:
        assert hasattr(question, name), name
    for name in [*agreed, *fields]:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(question, name, None)


def test_a_judgement_is_a_frozen_value_with_the_agreed_fields() -> None:
    """Everything the feedback card shows after an answer, whichever way it went."""
    question = drawn(KNOWN_JIP, Direction.HANGUL_TO_TRANSLATION)
    judgement = judge_answer(question, TypedAnswer("house"))
    names = [field.name for field in dataclasses.fields(judgement)]

    assert isinstance(judgement, VocabJudgement)
    assert names == ["correct", "korean", "translations", "correct_option"]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(judgement, name, None)


# ---------------------------------------------------------------------------------
# Answer mode
# ---------------------------------------------------------------------------------


def test_a_word_with_no_memory_is_asked_by_multiple_choice() -> None:
    """Nothing is known yet, so the first sight of a word is never a blank field."""
    assert answer_mode(None) is AnswerMode.CHOICE


@pytest.mark.parametrize(
    ("stability", "mode"),
    [
        pytest.param(0.1, AnswerMode.CHOICE, id="a-tenth-of-a-day"),
        pytest.param(1.99, AnswerMode.CHOICE, id="just-under"),
        pytest.param(2.0, AnswerMode.TYPING, id="exactly-the-threshold"),
        pytest.param(2.01, AnswerMode.TYPING, id="just-over"),
        pytest.param(365.0, AnswerMode.TYPING, id="a-year"),
    ],
)
def test_the_mode_turns_over_at_the_threshold(stability: float, mode: AnswerMode) -> None:
    """Typing starts *at* 2.0 days, not above it: the boundary is checked on both sides."""
    assert answer_mode(with_stability(stability)) is mode


@pytest.mark.parametrize(
    ("familiarity", "mode"),
    [
        pytest.param(Familiarity.NEW, AnswerMode.CHOICE, id="new"),
        pytest.param(Familiarity.A_LITTLE, AnswerMode.CHOICE, id="a_little"),
        pytest.param(Familiarity.WELL, AnswerMode.TYPING, id="well"),
        pytest.param(Familiarity.VERY_WELL, AnswerMode.TYPING, id="very_well"),
    ],
)
def test_the_familiarity_a_word_was_added_with_decides_its_first_mode(
    familiarity: Familiarity, mode: AnswerMode
) -> None:
    """The threshold sits between the `a_little` and `well` seeds, which is why it is 2.0. A seed
    lands in all four directions, so each of them starts in the same mode."""
    memories = make_word(1, "집", "house", familiarity=familiarity).memories

    assert [answer_mode(memories[direction]) for direction in Direction] == [mode] * 4


def with_direction_stability(direction: Direction, stability: float) -> VocabularyWord:
    """집 whose `direction` memory sits at `stability` days, every other direction at the
    `a_little` seed's 1.3: the ticket's own example of two directions in two modes."""
    memories = same_memory(memory_of(Familiarity.A_LITTLE))
    memories[direction] = with_stability(stability)
    return dataclasses.replace(JIP, familiarity=Familiarity.A_LITTLE, memories=memories)


def modes_by_direction(word: VocabularyWord) -> dict[Direction, AnswerMode]:
    """The mode `build_question` picks for `word` in each direction, distractors available."""
    return {
        direction: drawn(word, direction, candidates=CANDIDATES).mode for direction in Direction
    }


@pytest.mark.parametrize("strong", DIRECTIONS, ids=DIRECTION_IDS)
def test_the_mode_follows_the_memory_of_the_direction_asked(strong: Direction) -> None:
    """One direction at 3 days of stability, the other three at 1.3 (vocab-directions T01): a
    question in the strong direction is typed, a question in any other is tapped. The mode is
    decided per direction, from that direction's memory alone."""
    word = with_direction_stability(strong, 3.0)
    assert memory_of(Familiarity.A_LITTLE).stability < TYPING_STABILITY_DAYS  # sanity

    modes = modes_by_direction(word)

    assert modes[strong] is AnswerMode.TYPING
    assert [modes[other] for other in Direction if other is not strong] == [AnswerMode.CHOICE] * 3


@pytest.mark.parametrize("weak", DIRECTIONS, ids=DIRECTION_IDS)
def test_a_direction_with_no_memory_is_tapped_while_the_others_are_typed(weak: Direction) -> None:
    """A word learned in three directions and never asked in the fourth: that fourth is a first
    sight, so it is multiple choice, whatever the other three know."""
    memories = same_memory(memory_of(Familiarity.WELL))
    memories[weak] = None
    word = dataclasses.replace(JIP, memories=memories)

    modes = modes_by_direction(word)

    assert modes[weak] is AnswerMode.CHOICE
    assert [modes[other] for other in Direction if other is not weak] == [AnswerMode.TYPING] * 3


def test_a_lapse_drops_a_strong_word_back_to_multiple_choice() -> None:
    """About nine days of stability, missed on its due date: the word is weak again, and the
    exercise meets it where it is rather than keep asking it to type."""
    strong = memory_of(Familiarity.VERY_WELL)
    miss = grade_for(correct=False, mode=AnswerMode.TYPING)

    lapsed, _ = apply_grade(strong, miss, strong.next_review, fuzzing=False)

    assert 8 <= strong.stability <= 10
    assert answer_mode(strong) is AnswerMode.TYPING
    assert answer_mode(lapsed) is AnswerMode.CHOICE


# ---------------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("correct", "mode", "grade"),
    [
        pytest.param(False, AnswerMode.CHOICE, Grade.AGAIN, id="wrong-choice"),
        pytest.param(False, AnswerMode.TYPING, Grade.AGAIN, id="wrong-typing"),
        pytest.param(True, AnswerMode.CHOICE, Grade.HARD, id="right-choice"),
        pytest.param(True, AnswerMode.TYPING, Grade.GOOD, id="right-typing"),
    ],
)
def test_the_grade_for_an_outcome_and_a_mode(
    correct: bool, mode: AnswerMode, grade: Grade
) -> None:
    """The whole mapping, exhaustively: typing weighs more than tapping, and anything wrong is
    a lapse whichever way it was asked.

    A wrong entry here is silent in production - nothing raises, the word merely comes back at
    the wrong interval. This table is what stands in its way.
    """
    assert grade_for(correct=correct, mode=mode) is grade


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
@pytest.mark.parametrize("correct", [True, False], ids=["right", "wrong"])
def test_no_answer_ever_earns_easy(correct: bool, mode: AnswerMode) -> None:
    """`easy` belongs to the "very well" seed alone: typed-right as easy was tried while
    scoping and rejected, because stability reached 77 days by the third answer."""
    assert grade_for(correct=correct, mode=mode) is not Grade.EASY


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_the_direction_never_changes_the_grade_of_a_typed_answer(direction: Direction) -> None:
    """Hearing a word is harder than reading it, but each direction has its own memory
    (vocab-directions T01), so the difficulty is already the memory's, never the grade's."""
    question = drawn(KNOWN_JIP, direction)

    right = judge_answer(question, TypedAnswer(question.accepted_answers[0]))
    wrong = judge_answer(question, TypedAnswer("완전히 다른"))

    assert question.mode is AnswerMode.TYPING
    assert grade_for(correct=right.correct, mode=question.mode) is Grade.GOOD
    assert grade_for(correct=wrong.correct, mode=question.mode) is Grade.AGAIN


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_the_direction_never_changes_the_grade_of_a_tapped_answer(direction: Direction) -> None:
    """The same by multiple choice: right is `hard` in every direction, wrong is `again`."""
    question = drawn(JIP, direction, candidates=CANDIDATES)
    assert question.correct_index is not None
    other = (question.correct_index + 1) % len(question.options)

    right = judge_answer(question, ChoiceAnswer(question.correct_index))
    wrong = judge_answer(question, ChoiceAnswer(other))

    assert question.mode is AnswerMode.CHOICE
    assert grade_for(correct=right.correct, mode=question.mode) is Grade.HARD
    assert grade_for(correct=wrong.correct, mode=question.mode) is Grade.AGAIN


# ---------------------------------------------------------------------------------
# Liveness, across `exercises/` and `srs/`
# ---------------------------------------------------------------------------------


def test_a_word_answered_right_every_time_reaches_typing_and_keeps_growing() -> None:
    """The regression test for the deadlock found while scoping this epic.

    A new word answered right on each of its own due dates: the mode from the rule, the grade
    from the mapping, the next state from `srs/`. With FSRS's default learning steps a `hard`
    never leaves the first step, so the word would come back in a minute forever and never
    reach typing. Nothing would raise; the user would simply be stuck tapping.
    """
    modes, states = answered_in_turn(None, correct=True, answers=6)
    stabilities = [state.stability for state in states]

    assert modes == [AnswerMode.CHOICE, AnswerMode.CHOICE] + [AnswerMode.TYPING] * 4
    assert modes.index(AnswerMode.TYPING) == 2
    assert all(earlier < later for earlier, later in pairwise(stabilities))
    assert min(state.next_review - state.last_review for state in states) >= DAY


def test_a_word_answered_wrong_every_time_stays_in_multiple_choice() -> None:
    """The other end of the same chain: repeated misses never promote a word to typing, and
    never make it look stronger than it is."""
    modes, states = answered_in_turn(None, correct=False, answers=6)
    stabilities = [state.stability for state in states]

    assert modes == [AnswerMode.CHOICE] * 6
    assert all(earlier >= later for earlier, later in pairwise(stabilities))
    assert min(state.next_review - state.last_review for state in states) >= DAY


def test_a_word_added_as_well_known_starts_typing_and_falls_back_after_one_miss() -> None:
    """Both sides of the threshold in one history: typed from the first question, tapped again
    the moment it is missed."""
    modes, _ = answered_in_turn(memory_of(Familiarity.WELL), correct=False, answers=2)

    assert modes == [AnswerMode.TYPING, AnswerMode.CHOICE]


# ---------------------------------------------------------------------------------
# Building a question
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "prompt", "speech", "accepted"),
    [
        (Direction.HANGUL_TO_TRANSLATION, "집", None, ("house", "home")),
        (Direction.TRANSLATION_TO_HANGUL, "house, home", None, ("집",)),
        (Direction.VOICE_TO_HANGUL, None, "집", ("집",)),
        (Direction.VOICE_TO_TRANSLATION, None, "집", ("house", "home")),
    ],
    ids=DIRECTION_IDS,
)
def test_a_typed_question_in_each_direction(
    direction: Direction, prompt: str | None, speech: str | None, accepted: tuple[str, ...]
) -> None:
    """The ticket's direction table: which side is shown, which is spoken, which is answered.

    A voice question has no prompt at all, so nothing on the page spells out the word the user
    is supposed to be recognising by ear. Distractors are available and deliberately unused:
    the mode follows the word's memory, never the size of the vocabulary.
    """
    question = drawn(KNOWN_JIP, direction, candidates=CANDIDATES)

    assert question.word_id == KNOWN_JIP.id
    assert question.direction is direction
    assert question.mode is AnswerMode.TYPING
    assert (question.prompt, question.speech) == (prompt, speech)
    assert question.accepted_answers == accepted
    assert not question.options
    assert question.correct_index is None


@pytest.mark.parametrize(
    ("direction", "prompt", "speech", "correct"),
    [
        (Direction.HANGUL_TO_TRANSLATION, "집", None, "house, home"),
        (Direction.TRANSLATION_TO_HANGUL, "house, home", None, "집"),
        (Direction.VOICE_TO_HANGUL, None, "집", "집"),
        (Direction.VOICE_TO_TRANSLATION, None, "집", "house, home"),
    ],
    ids=DIRECTION_IDS,
)
def test_a_multiple_choice_question_in_each_direction(
    direction: Direction, prompt: str | None, speech: str | None, correct: str
) -> None:
    """Four options, exactly one of them right, and the index points at it.

    The correct option appears once and once only: a second copy would make a right answer
    unreachable through the index the question publishes.
    """
    question = drawn(JIP, direction, candidates=CANDIDATES)

    assert question.mode is AnswerMode.CHOICE
    assert (question.prompt, question.speech) == (prompt, speech)
    assert len(question.options) == 4
    assert question.options.count(correct) == 1
    assert correct_option(question) == correct
    assert not question.accepted_answers


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_a_word_that_could_also_be_right_is_never_offered_as_an_option(
    direction: Direction,
) -> None:
    """가정 means "home" too, so tapping it would be a right answer marked wrong - and in the
    other direction it answers the prompt "house, home" as well as 집 does. 집! keys the same
    as 집, so it is the same word however differently it is spelled, and its own translation
    collides with nothing, so only the match-key rule can keep it out.

    Fifty seeds, because a candidate excluded only sometimes is the worst kind of bug here.
    """
    options = options_across_seeds(direction, COLLIDING_CANDIDATES)

    assert "가정" not in options
    assert "집!" not in options
    assert [option for option in options if "family" in option] == []
    assert [option for option in options if "residence" in option] == []
    assert len(options) == 4 * len(SEEDS)


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_the_options_are_pairwise_distinct(direction: Direction) -> None:
    """물 and 식수 both translate "water": on the translation side they are one option, and two
    identical buttons would make one of them wrong for no reason the user can see."""
    for value in SEEDS:
        question = drawn(JIP, direction, candidates=COLLIDING_CANDIDATES, seed_value=value)

        assert len(set(question.options)) == len(question.options) == 4


def test_options_that_would_look_alike_are_never_offered_together() -> None:
    """`water` and `Water!` are judged alike, so as buttons they would read as one option."""
    lookalikes = (
        MUL,
        make_word(8, "생수", "Water!"),
        make_word(9, "음료수", "water."),
        SAGWA,
        CHAEK,
    )
    for value in SEEDS:
        question = drawn(
            JIP, Direction.HANGUL_TO_TRANSLATION, candidates=lookalikes, seed_value=value
        )
        waters = [option for option in question.options if "water" in option.casefold()]

        assert len(waters) <= 1
        assert len(question.options) == 4


def test_the_target_in_the_candidate_list_is_only_ever_the_correct_option() -> None:
    """T03 hands over the whole vocabulary, the word being asked included."""
    for value in SEEDS:
        question = drawn(
            JIP, Direction.HANGUL_TO_TRANSLATION, candidates=(JIP, *CANDIDATES), seed_value=value
        )

        assert question.options.count("house, home") == 1
        assert correct_option(question) == "house, home"


def test_the_correct_option_reaches_every_position() -> None:
    """A builder that always put the right answer last would be learned in one session."""
    indexes = {
        drawn(
            JIP, Direction.HANGUL_TO_TRANSLATION, candidates=CANDIDATES, seed_value=value
        ).correct_index
        for value in SEEDS
    }

    assert indexes == {0, 1, 2, 3}


def test_the_same_seed_builds_the_same_question() -> None:
    """Injected randomness: a question can be rebuilt exactly, options and index alike."""
    first = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=CANDIDATES, seed_value=11)
    second = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=CANDIDATES, seed_value=11)

    assert first == second


@pytest.mark.parametrize(
    ("candidates", "options"),
    [
        pytest.param((SAGWA, BAE, MUL, CHAEK), 4, id="four-eligible"),
        pytest.param((SAGWA, BAE, MUL), 4, id="three-eligible"),
        pytest.param((SAGWA, BAE), 3, id="two-eligible"),
        pytest.param((GAJEONG, SAGWA, BAE), 3, id="two-eligible-and-one-refused"),
        pytest.param((SAGWA,), 2, id="one-eligible"),
        pytest.param((GAJEONG, SAGWA), 2, id="one-eligible-and-one-refused"),
    ],
)
def test_a_thin_vocabulary_gives_a_shorter_list_of_options(
    candidates: tuple[VocabularyWord, ...], options: int
) -> None:
    """Up to three distractors, and fewer when the vocabulary cannot supply three eligible
    ones - never a padded list, and never fewer than two options."""
    question = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=candidates)

    assert question.mode is AnswerMode.CHOICE
    assert len(question.options) == options
    assert correct_option(question) == "house, home"


@pytest.mark.parametrize(
    "candidates",
    [
        pytest.param((), id="no-candidates-at-all"),
        pytest.param((GAJEONG,), id="only-a-word-sharing-a-translation"),
        pytest.param((JIP,), id="only-the-target-itself"),
    ],
)
def test_a_question_with_no_eligible_distractor_is_asked_by_typing(
    candidates: tuple[VocabularyWord, ...],
) -> None:
    """A two-option question with one impossible option is not a question. The mode reported is
    the mode actually used, so the grade follows it."""
    question = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=candidates)

    assert question.mode is AnswerMode.TYPING
    assert not question.options
    assert question.correct_index is None
    assert question.accepted_answers == ("house", "home")


# ---------------------------------------------------------------------------------
# Judging a typed translation
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("accepted", "answer", "right"),
    [
        pytest.param(("house", "home"), "house", True, id="the-first-translation"),
        pytest.param(("house", "home"), "Home", True, id="the-second-capitalised"),
        pytest.param(("house", "home"), "  home  ", True, id="surrounded-by-spaces"),
        pytest.param(("house", "home"), "HOUSE!", True, id="shouted-with-punctuation"),
        pytest.param(("house", "home"), "hous", False, id="a-letter-short"),
        pytest.param(("house", "home"), "houses", False, id="a-letter-too-many"),
        pytest.param(("house", "home"), "house home", False, id="both-translations-at-once"),
        pytest.param(("house", "home"), "house, home", True, id="both-comma-separated"),
        pytest.param(("house", "home"), "home; house", True, id="both-semicolon-separated"),
        pytest.param(("house", "home"), "house, homes", False, id="one-of-two-wrong"),
        pytest.param(("house", "home"), "house, ...", False, id="one-of-two-punctuation-only"),
        pytest.param(("house", "home"), ",", False, id="a-lone-comma"),
        pytest.param(("fun (short form)",), "fun", True, id="parentheses-left-out"),
        pytest.param(("fun (short form)",), "fun (short form)", True, id="parentheses-kept"),
        pytest.param(("fun (short form)",), "Fun (Short Form)!", True, id="parentheses-shouted"),
        pytest.param(("fun (short form)",), "fun short form", True, id="parentheses-unbracketed"),
        pytest.param(("fun (short form)",), "short form", False, id="only-the-parentheses"),
        pytest.param(("fun (short form)",), "fun (long form)", False, id="other-parentheses"),
        pytest.param(
            ("fun (short form)", "interesting (short form)"),
            "fun (short form), interesting",
            True,
            id="both-one-with-parentheses",
        ),
        pytest.param(("(to) eat",), "eat", True, id="leading-parentheses-left-out"),
        pytest.param(
            ("to want (a thing, a person)",), "to want", True, id="comma-inside-parentheses"
        ),
        pytest.param(("house", "home"), "", False, id="nothing-typed"),
        pytest.param(("house", "home"), "   ", False, id="whitespace-only"),
        pytest.param(("café",), "cafe", True, id="accent-dropped"),
        pytest.param(("café",), "CAFÉ", True, id="accent-kept-and-shouted"),
        pytest.param(("café",), "Café.", True, id="accent-and-full-stop"),
        pytest.param(("café",), "caf", False, id="a-letter-short-with-an-accent"),
        pytest.param(("to eat",), "to  eat", True, id="doubled-space"),
        pytest.param(("to eat",), "to-eat", True, id="hyphen-for-a-space"),
        pytest.param(("to eat",), "to eat!", True, id="exclamation-mark"),
        pytest.param(("to eat",), "toeat", False, id="space-left-out"),
        pytest.param(("to eat",), "eat", False, id="half-the-expression"),
        pytest.param(("ice-cream",), "ice cream", True, id="space-for-a-hyphen"),
        pytest.param(("ice-cream",), "ice/cream", True, id="slash-for-a-hyphen"),
        pytest.param(("ice-cream",), "ice_cream", True, id="underscore-for-a-hyphen"),
        pytest.param(("ice-cream",), "icecream", False, id="hyphen-left-out-entirely"),
        pytest.param(("don't",), "dont", True, id="apostrophe-left-out"),
        pytest.param(("don't",), "don’t", True, id="curly-apostrophe"),
        pytest.param(("don't",), "Don't", True, id="capitalised-with-an-apostrophe"),
        pytest.param(("don't",), "do not", False, id="spelled-out"),
        pytest.param(("naïve",), "naive", True, id="diaeresis-dropped"),
        pytest.param(("naïve",), "NAIVE", True, id="diaeresis-dropped-and-shouted"),
        pytest.param(("naïve",), "native", False, id="one-letter-off"),
        pytest.param(("...",), "", False, id="nothing-typed-against-punctuation-only"),
        pytest.param(("...",), "   ", False, id="whitespace-against-punctuation-only"),
        pytest.param(("...",), "?!", False, id="punctuation-against-punctuation-only"),
    ],
)
def test_a_typed_translation(accepted: tuple[str, ...], answer: str, right: bool) -> None:
    """Case, accents, punctuation and extra whitespace never make a different translation, and
    any of a word's translations counts, as do several of them separated by commas, each with or
    without what it has in parentheses; there is no typo tolerance.

    Dropping a row here is a weakened contract, like a numeral table: each one is a way an
    answer really arrives, and judging it the wrong way teaches the user something false.
    """
    assert is_right(typed_question("단어", *accepted), TypedAnswer(answer)) is right


# ---------------------------------------------------------------------------------
# Judging typed Hangul
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("direction", TO_HANGUL, ids=TO_HANGUL_IDS)
@pytest.mark.parametrize(
    ("answer", "right"),
    [
        pytest.param("사과", True, id="exactly-as-stored"),
        pytest.param(nfd("사과", 4), True, id="decomposed-by-an-input-method"),
        pytest.param("사 과", True, id="an-inner-space"),
        pytest.param(" 사과 ", True, id="surrounded-by-spaces"),
        pytest.param("사과.", True, id="a-trailing-full-stop"),
        pytest.param("샤과", False, id="one-vowel-off"),
        pytest.param("사과요", False, id="an-extra-syllable"),
        pytest.param("ㅅㅏㄱㅘ", False, id="compatibility-jamo-never-compose"),
        pytest.param("apple", False, id="the-translation-instead"),
        pytest.param("", False, id="nothing-typed"),
    ],
)
def test_typed_hangul(direction: Direction, answer: str, right: bool) -> None:
    """Spacing, punctuation and decomposition never make a different word - a phone keyboard
    sends decomposed jamo, and 띄어쓰기 is inconsistent among native speakers too - while one
    vowel off is exactly the skill being tested and a string of keyboard jamo is not a word.

    The rule is `korean/hangul.py`'s match key, so the whole project agrees on "the same word".
    """
    target = make_word(9, "사과", "apple", familiarity=Familiarity.WELL)

    assert is_right(drawn(target, direction), TypedAnswer(answer)) is right


@pytest.mark.parametrize("direction", TO_HANGUL, ids=TO_HANGUL_IDS)
@pytest.mark.parametrize(
    ("answer", "right"),
    [
        pytest.param("하다", True, id="parentheses-left-out"),
        pytest.param("하다 (do)", True, id="parentheses-kept"),
        pytest.param("do", False, id="only-the-parentheses"),
    ],
)
def test_typed_hangul_with_or_without_its_parentheses(
    direction: Direction, answer: str, right: bool
) -> None:
    """A Korean side with a parenthesised part accepts the answer with or without it."""
    target = make_word(9, "하다 (do)", "to do", familiarity=Familiarity.WELL)

    assert is_right(drawn(target, direction), TypedAnswer(answer)) is right


# ---------------------------------------------------------------------------------
# Judging a choice, and "I don't know"
# ---------------------------------------------------------------------------------


def test_the_right_option_is_right_and_every_other_one_is_wrong() -> None:
    """Tapping the option the question calls correct, then each of the others in turn."""
    question = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=CANDIDATES)
    assert question.correct_index is not None

    verdicts = [is_right(question, ChoiceAnswer(index)) for index in range(len(question.options))]

    assert verdicts.count(True) == 1
    assert verdicts[question.correct_index] is True


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(ChoiceAnswer(-1), id="a-negative-index"),
        pytest.param(ChoiceAnswer(4), id="one-past-the-last-option"),
        pytest.param(ChoiceAnswer(99), id="far-out-of-range"),
        pytest.param(TypedAnswer("house"), id="text-for-a-tapped-question"),
        pytest.param(TypedAnswer(""), id="blank-text-for-a-tapped-question"),
    ],
)
def test_a_malformed_answer_to_a_tapped_question_is_refused(answer: SubmittedAnswer) -> None:
    """Refused, not scored: T03 answers 422 and leaves the question unconsumed, so a client bug
    never costs the user a word's memory. An out-of-range index is not "the wrong option"."""
    question = drawn(JIP, Direction.HANGUL_TO_TRANSLATION, candidates=CANDIDATES)
    assert len(question.options) == 4

    with pytest.raises(MalformedAnswerError):
        judge_answer(question, answer)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(ChoiceAnswer(0), id="the-first-index"),
        pytest.param(ChoiceAnswer(-1), id="a-negative-index"),
    ],
)
def test_an_index_answer_to_a_typed_question_is_refused(answer: SubmittedAnswer) -> None:
    """A typed question publishes no options, so an index answers nothing."""
    with pytest.raises(MalformedAnswerError):
        judge_answer(drawn(KNOWN_JIP, Direction.HANGUL_TO_TRANSLATION), answer)


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_i_dont_know_is_wrong_in_both_modes(direction: Direction) -> None:
    """Offered in both modes and counted as a miss, so nobody guesses their way through a
    multiple-choice question they cannot answer."""
    tapped = drawn(JIP, direction, candidates=CANDIDATES)
    typed = drawn(KNOWN_JIP, direction)

    assert is_right(tapped, DontKnowAnswer()) is False
    assert is_right(typed, DontKnowAnswer()) is False
    assert grade_for(correct=False, mode=tapped.mode) is Grade.AGAIN


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_a_judgement_always_carries_the_word_however_the_answer_went(direction: Direction) -> None:
    """The feedback card shows the Korean and every translation after any answer, so a miss
    teaches the word rather than only reporting the loss - and a tapped question also says
    which option was the right one."""
    tapped = drawn(JIP, direction, candidates=CANDIDATES)
    assert tapped.correct_index is not None
    other = (tapped.correct_index + 1) % len(tapped.options)

    right = judge_answer(tapped, ChoiceAnswer(tapped.correct_index))
    wrong = judge_answer(tapped, ChoiceAnswer(other))
    missed = judge_answer(drawn(KNOWN_JIP, direction), DontKnowAnswer())

    for judgement in (right, wrong, missed):
        assert judgement.korean == "집"
        assert judgement.translations == ("house", "home")
    assert right.correct_option == correct_option(tapped)
    assert wrong.correct_option == correct_option(tapped)
    assert missed.correct_option is None


def test_judging_the_same_question_twice_gives_the_same_judgement() -> None:
    """Judging is pure: consuming a question is T03's job, and a question that changed under
    judging would score a word twice from one attempt."""
    question = drawn(KNOWN_JIP, Direction.HANGUL_TO_TRANSLATION)

    once = judge_answer(question, TypedAnswer("house"))
    twice = judge_answer(question, TypedAnswer("house"))

    assert once == twice
    assert once.correct is True
    assert question == drawn(KNOWN_JIP, Direction.HANGUL_TO_TRANSLATION)


# ---------------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------------

VOCAB_MODULE = "oral_korean.exercises.vocab"
SESSION_MODULE = "oral_korean.exercises.vocab_session"

FORBIDDEN_FOR_VOCAB = (*FORBIDDEN_IMPORTS, "oral_korean.config")
"""What this exercise may never reach for: `tts/`, `api/`, `storage/`, `sqlite3` and the rest,
plus `config`, which `exercises/` has no business reading. `korean/` and `srs/` stay open."""


def vocab_modules() -> list[ModuleType]:
    """`vocab.py`, plus `vocab_session.py` when the implementation split the session out."""
    names = [VOCAB_MODULE]
    if importlib.util.find_spec(SESSION_MODULE) is not None:
        names.append(SESSION_MODULE)
    return [importlib.import_module(name) for name in names]


def reaches_outside(imported: set[str]) -> list[str]:
    """The imported names that fall outside the exercises layer, sorted for a stable message."""
    return sorted(name for name in imported if name.startswith(FORBIDDEN_FOR_VOCAB))


def test_the_vocab_modules_import_nothing_outside_their_layer() -> None:
    """Read statically from the source, so an import hidden inside a function is caught too.

    `tests/test_layering.py` walks the whole package for the same rule; this names the modules
    this ticket adds, at the file where they are specified.
    """
    for module in vocab_modules():
        assert reaches_outside(imported_module_names(module)) == [], module.__name__


def test_the_layer_check_bites() -> None:
    """Otherwise the check above could look for names nobody ever writes and pass forever."""
    imported = {"oral_korean.storage.words", "sqlite3", "oral_korean.korean.hangul", "random"}

    assert reaches_outside(imported) == ["oral_korean.storage.words", "sqlite3"]


def test_the_vocab_modules_build_on_korean_and_srs_rather_than_repeat_them() -> None:
    """The Hangul key comes from `korean/hangul.py` and the grades from `srs/`: a second copy of
    either would drift, and a word judged the same in one place must be judged the same
    everywhere."""
    imported = set[str]().union(*(imported_module_names(module) for module in vocab_modules()))

    assert [name for name in imported if name.startswith("oral_korean.korean")] != []
    assert [name for name in imported if name.startswith("oral_korean.srs")] != []
