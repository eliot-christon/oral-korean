"""Tests for the vocabulary session plan: what is asked, in what order, and what is scored.

Written from vocab-sessions T02's acceptance criteria and test contract, before the
implementation, and they define the contract it satisfies. The rest of that ticket
(directions, modes, grading, building and judging) is pinned in
`tests/test_exercises_vocab.py`; this file is separate because the two subjects together do not
fit in one module, which is also the split the ticket itself suggests for the production code.
Everything is imported from `oral_korean.exercises.vocab`, so a `vocab_session.py` split must
be re-exported from there.

- `SessionKind` (`StrEnum`): `LEARN` ("learn"), `REVIEW` ("review").
- `ItemKind` (`StrEnum`): `PRESENTATION` ("presentation"), `QUESTION` ("question").
- `SessionItem` (frozen): `number` (1-based, the handle an answer is recorded against), `kind`,
  `word`, `scored`.
- `WordResult` (frozen): `word_id`, `correct`. `SessionSummary` (frozen): `results`,
  `word_count`, `correct_count`.
- `SessionPlan(kind, words)` with `next_item() -> SessionItem | None`,
  `record_answer(number, *, correct) -> None` and `summary() -> SessionSummary`.
- `SessionStateError(ValueError)`: a recording the plan refuses.

Decisions taken here that the ticket leaves open, flagged in the hand-back report:

1. **A presentation is done once it has been handed out**, while a question stands until it is
   answered. That is what makes "asking again does not skip a hard word" a property of the
   plan rather than of T03's route, and it is why a presentation cannot be recorded against.
2. **An answer is recorded against the item's `number`**, not the item value: an int is the
   whole handle T03 needs beside its own opaque item id.
3. **The plan takes the words themselves**, so an item carries the word T03 builds a question
   from, with no id-to-word map in between.

Pure calls throughout: no file, no patching, no clock, no HTTP. The plan chooses no direction
and no mode, so no memory state and no random source appear here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest
from conftest import signature_shape

from oral_korean.exercises.vocab import (
    ItemKind,
    SessionItem,
    SessionKind,
    SessionPlan,
    SessionStateError,
    SessionSummary,
    WordResult,
)
from oral_korean.exercises.vocab_words import VocabularyWord
from oral_korean.srs.memory import Familiarity

T0 = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
KINDS = list(SessionKind)
KIND_IDS = [kind.value for kind in KINDS]


def make_word(word_id: int, korean: str) -> VocabularyWord:
    """One stored word: the plan reads its id and its Korean, and nothing else about it."""
    return VocabularyWord(word_id, korean, ("word",), (), Familiarity.NEW, T0, None)


JIP = make_word(1, "집")
SAGWA = make_word(3, "사과")


def numbered_words(count: int) -> list[VocabularyWord]:
    """`count` distinct words, so a long session never collides by id or by Korean."""
    return [make_word(100 + n, chr(0xAC00 + n)) for n in range(count)]


def always_right(_item: SessionItem) -> bool:
    """Every question answered right."""
    return True


def always_wrong(_item: SessionItem) -> bool:
    """Every question answered wrong."""
    return False


def first_attempt_wrong(word_id: int) -> Callable[[SessionItem], bool]:
    """`word_id` missed on its scored question and answered right ever after."""
    return lambda item: not (item.scored and item.word.id == word_id)


def word_always_wrong(word_id: int) -> Callable[[SessionItem], bool]:
    """Every question for `word_id` answered wrong, every other one right."""
    return lambda item: item.word.id != word_id


def run_session(plan: SessionPlan, answer: Callable[[SessionItem], bool]) -> list[SessionItem]:
    """Every item `plan` hands out, each question answered as `answer` decides.

    The cap is the termination proof: a plan that never ends fails here with a message instead
    of hanging the suite.
    """
    handed: list[SessionItem] = []
    while (item := plan.next_item()) is not None:
        handed.append(item)
        if item.kind is ItemKind.QUESTION:
            plan.record_answer(item.number, correct=answer(item))
        assert len(handed) <= 100, "the session handed out 100 items without ending"
    return handed


def shape(items: Sequence[SessionItem]) -> list[tuple[ItemKind, str, bool]]:
    """Each handed-out item as its kind, the word's Korean, and whether it is scored."""
    return [(item.kind, item.word.korean, item.scored) for item in items]


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


def test_the_session_and_item_kinds_have_their_wire_values() -> None:
    """T03 serialises both: a learn or review session, a presentation or a question."""
    assert KIND_IDS == ["learn", "review"]
    assert [kind.value for kind in ItemKind] == ["presentation", "question"]
    assert SessionKind("review") is SessionKind.REVIEW


def test_a_refused_recording_is_a_value_error() -> None:
    """One family to catch, as the rest of the project's refusals already are."""
    assert issubclass(SessionStateError, ValueError)


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        pytest.param(SessionPlan, ["kind", "words"], [], id="SessionPlan"),
        pytest.param(SessionPlan.next_item, ["self"], [], id="next_item"),
        pytest.param(SessionPlan.record_answer, ["self", "number"], ["correct"], id="record"),
        pytest.param(SessionPlan.summary, ["self"], [], id="summary"),
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """`correct` is keyword-only: a stray positional `False` would record the wrong outcome and
    nothing at runtime would notice. The unbound methods carry their `self`."""
    assert signature_shape(function) == (positional, keyword_only)


def test_the_session_values_are_frozen_with_the_agreed_fields() -> None:
    """An item is the handle an answer is recorded against; the summary is what T04 shows."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP])
    item = plan.next_item()
    assert item is not None
    plan.record_answer(item.number, correct=True)
    summary = plan.summary()
    result = summary.results[0]

    assert isinstance(summary, SessionSummary)
    assert [field.name for field in dataclasses.fields(item)] == [
        "number",
        "kind",
        "word",
        "scored",
    ]
    assert [field.name for field in dataclasses.fields(summary)] == [
        "results",
        "word_count",
        "correct_count",
    ]
    assert [field.name for field in dataclasses.fields(result)] == ["word_id", "correct"]
    for value in (item, summary, result):
        for field in dataclasses.fields(value):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(value, field.name, None)


# ---------------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------------


def test_a_learn_session_presents_each_word_before_asking_it() -> None:
    """A new word is shown openly - Korean, translations, audio - and only then asked.

    Nothing records an answer for a presentation here, so this also pins that a presentation is
    done once handed out: the next call moves on to the question instead of showing it again.
    """
    plan = SessionPlan(SessionKind.LEARN, [JIP, SAGWA])

    items = run_session(plan, always_right)

    assert shape(items) == [
        (ItemKind.PRESENTATION, "집", False),
        (ItemKind.QUESTION, "집", True),
        (ItemKind.PRESENTATION, "사과", False),
        (ItemKind.QUESTION, "사과", True),
    ]
    assert [item.number for item in items] == [1, 2, 3, 4]


def test_a_review_session_asks_each_word_once() -> None:
    """Nothing to present: a due word has been learned already."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP, SAGWA])

    items = run_session(plan, always_right)

    assert shape(items) == [(ItemKind.QUESTION, "집", True), (ItemKind.QUESTION, "사과", True)]


def test_a_missed_word_comes_back_unscored_at_the_end_of_the_queue() -> None:
    """The practice question is not an FSRS review: the word's grade was settled by its first
    attempt, and asking it again minutes later only inflates difficulty."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP, SAGWA])

    items = run_session(plan, first_attempt_wrong(JIP.id))

    assert shape(items) == [
        (ItemKind.QUESTION, "집", True),
        (ItemKind.QUESTION, "사과", True),
        (ItemKind.QUESTION, "집", False),
    ]


def test_a_word_missed_every_time_comes_back_twice_and_no_more() -> None:
    """Two practice questions per word is the cap, which is what makes a session end at all."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP, SAGWA])

    items = run_session(plan, word_always_wrong(JIP.id))

    assert shape(items) == [
        (ItemKind.QUESTION, "집", True),
        (ItemKind.QUESTION, "사과", True),
        (ItemKind.QUESTION, "집", False),
        (ItemKind.QUESTION, "집", False),
    ]


@pytest.mark.parametrize("count", [1, 3, 10], ids=["one-word", "three-words", "ten-words"])
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_session_of_nothing_but_wrong_answers_still_ends(kind: SessionKind, count: int) -> None:
    """At most three questions per word, whatever the user does: the plan is the only thing
    standing between a missed word and an endless session. Asked again once over, it still
    says the session is finished."""
    plan = SessionPlan(kind, numbered_words(count))

    items = run_session(plan, always_wrong)
    questions = [item for item in items if item.kind is ItemKind.QUESTION]

    assert len(questions) <= 3 * count
    assert plan.next_item() is None
    assert plan.next_item() is None


@pytest.mark.parametrize(
    "answer", [always_right, always_wrong], ids=["every-answer-right", "every-answer-wrong"]
)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_every_word_gets_exactly_one_scored_question(
    kind: SessionKind, answer: Callable[[SessionItem], bool]
) -> None:
    """FSRS sees a word's first attempt and nothing else, so the practice questions cannot
    score it twice in one session, in either direction."""
    words = numbered_words(4)
    plan = SessionPlan(kind, words)

    items = run_session(plan, answer)
    scored = [item for item in items if item.scored]

    assert [item.word.id for item in scored] == [word.id for word in words]
    assert all(item.kind is ItemKind.QUESTION for item in scored)


def test_asking_for_the_next_item_again_returns_the_same_unanswered_question() -> None:
    """No skipping a hard word by asking for the next one: the question stands until it is
    answered, which is what T03's `next` route relies on."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP, SAGWA])

    first = plan.next_item()
    assert first is not None
    assert plan.next_item() == first

    plan.record_answer(first.number, correct=True)
    second = plan.next_item()

    assert second is not None
    assert (second.number, second.word.id) == (first.number + 1, SAGWA.id)


# ---------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------


def test_recording_an_answer_twice_for_the_same_item_is_refused() -> None:
    """Answering consumes the question (the epic's rule): a second answer, after the correct
    one has been shown, would corrupt the word's memory."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP])
    item = plan.next_item()
    assert item is not None
    plan.record_answer(item.number, correct=True)

    with pytest.raises(SessionStateError):
        plan.record_answer(item.number, correct=False)


@pytest.mark.parametrize(
    "number", [pytest.param(1, id="not-handed-out-yet"), pytest.param(99, id="no-such-item")]
)
def test_recording_an_answer_for_an_item_never_handed_out_is_refused(number: int) -> None:
    """A client cannot answer a question the session has not asked, nor invent an item id."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP])

    with pytest.raises(SessionStateError):
        plan.record_answer(number, correct=True)


def test_recording_an_answer_for_a_presentation_is_refused() -> None:
    """A presentation shows everything by design; there is nothing to be right or wrong about."""
    plan = SessionPlan(SessionKind.LEARN, [JIP])
    item = plan.next_item()
    assert item is not None
    assert item.kind is ItemKind.PRESENTATION

    with pytest.raises(SessionStateError):
        plan.record_answer(item.number, correct=True)


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_session_over_no_words_at_all_is_refused(kind: SessionKind) -> None:
    """T03 answers 409 when there is nothing to learn or review; an empty plan is a bug, not a
    session that ends immediately."""
    with pytest.raises(ValueError):
        SessionPlan(kind, [])


@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_session_holding_the_same_word_twice_is_refused(kind: SessionKind) -> None:
    """One scored question per word: the same word given twice would be scored twice."""
    with pytest.raises(ValueError):
        SessionPlan(kind, [JIP, SAGWA, JIP])


# ---------------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------------


def test_the_summary_reports_each_words_first_attempt_and_the_totals() -> None:
    """집 was missed on its scored question and answered right on the practice one: the summary
    reports the attempt that counted, not the last one."""
    plan = SessionPlan(SessionKind.REVIEW, [JIP, SAGWA])

    run_session(plan, first_attempt_wrong(JIP.id))
    summary = plan.summary()

    assert summary.results == (
        WordResult(word_id=JIP.id, correct=False),
        WordResult(word_id=SAGWA.id, correct=True),
    )
    assert (summary.word_count, summary.correct_count) == (2, 1)


def test_the_summary_of_a_session_answered_perfectly_counts_every_word() -> None:
    """The other end of the same report, in the order the words were given."""
    words = numbered_words(3)
    plan = SessionPlan(SessionKind.LEARN, words)

    run_session(plan, always_right)
    summary = plan.summary()

    assert [result.word_id for result in summary.results] == [word.id for word in words]
    assert all(result.correct for result in summary.results)
    assert (summary.word_count, summary.correct_count) == (3, 3)
    assert summary.word_count == len(summary.results)
