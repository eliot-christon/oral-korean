"""The session plan: what to ask next in a learn or review session, and what it scored.

Pure sequencing over an ordered list of words - no direction, no answer mode, no memory
state and no random source enter here: those are decided by whoever builds each item's
question (`vocab.py`, wired to HTTP by `vocab-sessions` T03). A wrong answer, scored or
practice, re-queues the word once more at the end of the queue, capped at two practice
repeats so a session that goes entirely wrong still ends.

Separate from `vocab.py` because it needs neither: the plan says "ask word X, scored or
not", nothing about how.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from oral_korean.exercises.vocab_words import VocabularyWord

MAX_PRACTICE_REPEATS: Final = 2
"""How many extra, unscored chances a missed word gets before the plan gives up on it."""


class SessionKind(StrEnum):
    """A learn session introduces new words; a review session serves due ones."""

    LEARN = "learn"
    REVIEW = "review"


class ItemKind(StrEnum):
    """What one item of a session is: shown openly, or something to answer."""

    PRESENTATION = "presentation"
    QUESTION = "question"


class SessionStateError(ValueError):
    """A recording the plan refuses: an unknown item, one already recorded, or a
    presentation, which carries nothing to be right or wrong about."""


@dataclass(frozen=True)
class SessionItem:
    """One item handed out by the plan.

    Attributes:
        number: 1-based, unique for the life of the plan - the handle an answer is
            recorded against.
        kind: shown openly, or asked.
        word: the word this item is about.
        scored: whether answering this item (a question only) counts as the word's one
            scored attempt for the session.
    """

    number: int
    kind: ItemKind
    word: VocabularyWord
    scored: bool


@dataclass(frozen=True)
class WordResult:
    """Whether a word's first, scored attempt was right."""

    word_id: int
    correct: bool


@dataclass(frozen=True)
class SessionSummary:
    """What to show at the end of a session."""

    results: tuple[WordResult, ...]
    word_count: int
    correct_count: int


class SessionPlan:
    """Sequences a learn or review session over `words`, one scored attempt each.

    Raises:
        ValueError: `words` is empty, or holds the same word twice - which would score it
            twice in one session.
    """

    def __init__(self, kind: SessionKind, words: Sequence[VocabularyWord]) -> None:
        if not words:
            raise ValueError("A session needs at least one word.")
        self._word_order = [word.id for word in words]
        if len(set(self._word_order)) != len(self._word_order):
            raise ValueError("A session cannot hold the same word twice.")
        self._first_results: dict[int, bool] = {}
        self._practice_counts: dict[int, int] = dict.fromkeys(self._word_order, 0)
        self._counter = 0
        self._queue: list[SessionItem] = []
        self._current_is_shown = False
        for word in words:
            if kind is SessionKind.LEARN:
                self._queue.append(self._new_item(ItemKind.PRESENTATION, word, scored=False))
            self._queue.append(self._new_item(ItemKind.QUESTION, word, scored=True))

    def next_item(self) -> SessionItem | None:
        """The next item to show: a presentation, a fresh question, or the one still
        pending. A presentation is handed out once and gone; a question stands - the same
        item, unchanged - until `record_answer` is called for it. `None` once the plan is
        finished.
        """
        if not self._queue:
            return None
        item = self._queue[0]
        if item.kind is ItemKind.PRESENTATION:
            self._queue.pop(0)
        else:
            self._current_is_shown = True
        return item

    def record_answer(self, number: int, *, correct: bool) -> None:
        """Record the outcome of the pending question numbered `number`.

        A wrong answer re-queues an unscored practice question for the same word, up to
        `MAX_PRACTICE_REPEATS` times. The word's first attempt (always its scored question,
        since a practice question only ever follows it) is what the summary reports.

        Raises:
            SessionStateError: `number` is not the currently pending question - unknown,
                not yet handed out by `next_item`, already recorded, or a presentation.
        """
        if (
            not self._current_is_shown
            or not self._queue
            or self._queue[0].kind is not ItemKind.QUESTION
            or self._queue[0].number != number
        ):
            raise SessionStateError(f"No pending question with number {number}.")
        item = self._queue.pop(0)
        self._current_is_shown = False
        self._apply_result(item, correct=correct)

    def summary(self) -> SessionSummary:
        """The outcome of every word given, in the order they were given."""
        results = tuple(
            WordResult(word_id=word_id, correct=self._first_results.get(word_id, False))
            for word_id in self._word_order
        )
        correct_count = sum(1 for result in results if result.correct)
        return SessionSummary(
            results=results, word_count=len(results), correct_count=correct_count
        )

    def _new_item(self, kind: ItemKind, word: VocabularyWord, *, scored: bool) -> SessionItem:
        self._counter += 1
        return SessionItem(number=self._counter, kind=kind, word=word, scored=scored)

    def _apply_result(self, item: SessionItem, *, correct: bool) -> None:
        word = item.word
        if word.id not in self._first_results:
            self._first_results[word.id] = correct
        if correct:
            return
        practices_so_far = self._practice_counts[word.id]
        if practices_so_far < MAX_PRACTICE_REPEATS:
            self._practice_counts[word.id] = practices_so_far + 1
            self._queue.append(self._new_item(ItemKind.QUESTION, word, scored=False))
