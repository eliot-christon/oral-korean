"""The session plan: what to ask next in a learn or review session, and what it scored.

Pure sequencing over a batch of words, each with the directions it is asked in (chosen by
`vocab.directions_to_ask`). No answer mode and no memory state enter here: those are decided
by whoever builds each item's question (`vocab.py`, wired to HTTP by `vocab-sessions` T03).

- **One scored question per (word, direction).** The batch is shuffled with the injected
  random source, and so is each word's list of directions. The scored questions are then
  spread out: each comes from the word with the most still to ask, never the word just
  asked while another word has questions left.
- **A learn session presents each word once**, right before its first question.
- **A wrong answer**, scored or practice, re-queues an unscored practice question for the
  same word and direction at the end of the queue, capped at two per (word, direction), so a
  session that goes entirely wrong still ends. Practice therefore follows every scored
  question.

Separate from `vocab.py` because it needs none of it: the plan says "ask word X in direction
D, scored or not", nothing about how.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from oral_korean.exercises.vocab_words import Direction, VocabularyWord

MAX_PRACTICE_REPEATS: Final = 2
"""How many extra, unscored chances a missed question gets before the plan gives up on it."""

type Batch = Sequence[tuple[VocabularyWord, Sequence[Direction]]]
"""The words of a session, each with the directions it is asked in."""


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
        direction: the direction a question is asked in; `None` for a presentation.
        scored: whether answering this item (a question only) counts as the one scored
            attempt of its word and direction for the session.
    """

    number: int
    kind: ItemKind
    word: VocabularyWord
    direction: Direction | None
    scored: bool


@dataclass(frozen=True)
class DirectionResult:
    """Whether a word's scored attempt in one direction was right."""

    direction: Direction
    correct: bool


@dataclass(frozen=True)
class WordResult:
    """How a word went: right only if every direction it was asked in was, each listed in
    `Direction` order. A direction not answered yet counts as not right."""

    word_id: int
    correct: bool
    directions: tuple[DirectionResult, ...]


@dataclass(frozen=True)
class SessionSummary:
    """What to show at the end of a session: per word, and in questions."""

    results: tuple[WordResult, ...]
    word_count: int
    correct_count: int
    question_count: int
    correct_question_count: int


@dataclass(frozen=True)
class SessionProgress:
    """How far a session has gone. A word is done once its every scored question is."""

    words_done: int
    word_count: int
    questions_done: int
    question_count: int


class SessionPlan:
    """Sequences a learn or review session over `batch`, one scored attempt per word and
    direction.

    Raises:
        ValueError: `batch` is empty, holds the same word twice, or gives a word no direction
            or the same direction twice - any of which would score something twice or never.
    """

    def __init__(
        self, kind: SessionKind, batch: Batch, *, rng: random.Random | None = None
    ) -> None:
        _check_batch(batch)
        source = rng if rng is not None else random.Random()
        self._asked: dict[int, tuple[Direction, ...]] = {
            word.id: tuple(directions) for word, directions in batch
        }
        self._results: dict[tuple[int, Direction], bool] = {}
        self._practice_counts: dict[tuple[int, Direction], int] = {}
        self._counter = 0
        self._current_is_shown = False
        self._queue: list[SessionItem] = []

        shuffled = [
            (word, source.sample(list(directions), len(directions))) for word, directions in batch
        ]
        source.shuffle(shuffled)
        presented: set[int] = set()
        for word, direction in _spread(shuffled):
            if kind is SessionKind.LEARN and word.id not in presented:
                presented.add(word.id)
                self._queue.append(self._new_item(ItemKind.PRESENTATION, word, None))
            self._queue.append(self._new_item(ItemKind.QUESTION, word, direction, scored=True))

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

        A wrong answer re-queues an unscored practice question for the same word and
        direction, up to `MAX_PRACTICE_REPEATS` times. The scored attempt is what the summary
        reports.

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
            _word_result(word_id, directions, self._results)
            for word_id, directions in self._asked.items()
        )
        return SessionSummary(
            results=results,
            word_count=len(results),
            correct_count=sum(result.correct for result in results),
            question_count=self._question_count(),
            correct_question_count=sum(self._results.values()),
        )

    def progress(self) -> SessionProgress:
        """Scored questions recorded so far, and the words they complete."""
        return SessionProgress(
            words_done=sum(
                all((word_id, direction) in self._results for direction in directions)
                for word_id, directions in self._asked.items()
            ),
            word_count=len(self._asked),
            questions_done=len(self._results),
            question_count=self._question_count(),
        )

    def _question_count(self) -> int:
        return sum(len(directions) for directions in self._asked.values())

    def _new_item(
        self,
        kind: ItemKind,
        word: VocabularyWord,
        direction: Direction | None,
        *,
        scored: bool = False,
    ) -> SessionItem:
        self._counter += 1
        return SessionItem(
            number=self._counter, kind=kind, word=word, direction=direction, scored=scored
        )

    def _apply_result(self, item: SessionItem, *, correct: bool) -> None:
        if item.direction is None:
            # Only a question is ever recorded; this narrows the type and says so.
            raise SessionStateError("A presentation carries no answer.")
        key = (item.word.id, item.direction)
        if item.scored:
            self._results[key] = correct
        if correct:
            return
        practices_so_far = self._practice_counts.get(key, 0)
        if practices_so_far < MAX_PRACTICE_REPEATS:
            self._practice_counts[key] = practices_so_far + 1
            self._queue.append(self._new_item(ItemKind.QUESTION, item.word, item.direction))


def _check_batch(batch: Batch) -> None:
    """Refuse a batch that would score something twice, or never."""
    if not batch:
        raise ValueError("A session needs at least one word.")
    ids = [word.id for word, _ in batch]
    if len(set(ids)) != len(ids):
        raise ValueError("A session cannot hold the same word twice.")
    for word, directions in batch:
        if not directions:
            raise ValueError(f"{word.korean} has no direction to be asked in.")
        if len(set(directions)) != len(directions):
            raise ValueError(f"{word.korean} is asked in the same direction twice.")


def _spread(batch: Batch) -> list[tuple[VocabularyWord, Direction]]:
    """Every (word, direction) of `batch`, spread so no word is asked twice in a row while
    another still has questions left.

    Each step takes the word with the most questions left, other than the one just asked,
    ties going to the earlier word in `batch`. Taking the most loaded first is what keeps the
    rule satisfiable to the end whenever it can be.
    """
    remaining = [(word, list(directions)) for word, directions in batch]
    order: list[tuple[VocabularyWord, Direction]] = []
    previous: int | None = None
    while any(directions for _, directions in remaining):
        candidates = [entry for entry in remaining if entry[1] and entry[0].id != previous]
        if not candidates:
            candidates = [entry for entry in remaining if entry[1]]
        word, directions = max(candidates, key=lambda entry: len(entry[1]))
        order.append((word, directions.pop(0)))
        previous = word.id
    return order


def _word_result(
    word_id: int,
    directions: tuple[Direction, ...],
    results: dict[tuple[int, Direction], bool],
) -> WordResult:
    """One word's scored attempts, in `Direction` order."""
    per_direction = tuple(
        DirectionResult(direction=direction, correct=results.get((word_id, direction), False))
        for direction in Direction
        if direction in directions
    )
    return WordResult(
        word_id=word_id,
        correct=all(result.correct for result in per_direction),
        directions=per_direction,
    )
