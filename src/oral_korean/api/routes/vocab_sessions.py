"""HTTP routes for learn and review sessions: presentations, questions, answers, scores.

Thin over vocab-sessions T02: this module chooses no direction or mode, judges no answer,
maps no grade and computes no memory. `exercises.vocab` builds and judges each question and
sequences the session, `srs.memory` applies the grade, `storage.words` chooses the words and
keeps the result, and `api/pending.py` and `api/audio.py` are the helpers shared with the
numbers exercise.

Two invariants live here, because only the server can keep them:

- **The answer never reaches the browser before it is submitted.** A question carries its
  opaque item id, never the word's id; the answer side only ever as one option among several;
  and the audio of a voice question by item id, never the Korean it speaks.
- **A word is scored at most once per session, from its first attempt.** Answering *takes*
  the item out of the store before anything is written, so of two answers racing for one
  item exactly one is judged; a malformed answer is refused before the take, so it consumes
  nothing. Each session also has its own lock, held by `next` and by an answer from the
  take to the plan's bookkeeping: two `next` calls at once (a React effect run twice), or a
  `next` landing while an answer is being scored, never hand out a second question for one
  item.

Sessions and items live in two plain dicts on `app.state`, like the numbers questions: a
restart loses a session, never a score, since a scored answer is written before its response.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Self

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from oral_korean.api.audio import synthesise_or_502
from oral_korean.api.pending import get_pending_or_404, store_pending, take_pending_or_404
from oral_korean.exercises.vocab import (
    ChoiceAnswer,
    Direction,
    DontKnowAnswer,
    ItemKind,
    MalformedAnswerError,
    SessionItem,
    SessionKind,
    SessionPlan,
    SubmittedAnswer,
    TypedAnswer,
    VocabJudgement,
    VocabQuestion,
    build_question,
    draw_direction,
    grade_for,
    judge_answer,
)
from oral_korean.exercises.vocab_words import VocabularyWord
from oral_korean.srs.memory import WordStatistics, apply_grade, statistics
from oral_korean.storage.words import AnswerContext, WordStore
from oral_korean.tts.cache import AudioCache

router = APIRouter(prefix="/vocab")

_AUDIO_ROUTE_NAME = "vocab_item_audio"

_SIZE_LIMITS = {SessionKind.LEARN: 20, SessionKind.REVIEW: 100}
_DEFAULT_SIZES = {SessionKind.LEARN: 5, SessionKind.REVIEW: 20}


class StartSessionRequest(BaseModel):
    """A learn or review session over at most `size` words, optionally of one tag."""

    kind: SessionKind
    tag: str | None = None
    directions: list[Direction] = Field(default_factory=lambda: list(Direction), min_length=1)
    size: int | None = None

    @model_validator(mode="after")
    def _size_within_its_kinds_range(self) -> Self:
        maximum = _SIZE_LIMITS[self.kind]
        if self.size is not None and not 1 <= self.size <= maximum:
            raise ValueError(f"A {self.kind} session takes 1 to {maximum} words.")
        return self


class StartSessionResponse(BaseModel):
    session_id: str
    kind: SessionKind
    word_count: int
    directions: list[Direction]


class Progress(BaseModel):
    """Words whose scored question has been answered, out of the session's words."""

    done: int
    total: int


class PresentationResponse(BaseModel):
    """A new word shown openly before it is asked: everything about it, nothing to answer."""

    type: Literal["presentation"] = "presentation"
    item_id: str
    korean: str
    translations: list[str]
    audio_url: str
    progress: Progress


class QuestionResponse(BaseModel):
    """A question as the browser sees it - never the word's id, never which option is right.

    `prompt` is null for a voice direction, `audio_url` for a written one, `options` for
    typing."""

    type: Literal["question"] = "question"
    item_id: str
    direction: Direction
    mode: str
    prompt: str | None
    audio_url: str | None
    options: list[str] | None
    scored: bool
    progress: Progress


class SummaryWord(BaseModel):
    korean: str
    translations: list[str]
    correct: bool


class SessionSummaryResponse(BaseModel):
    """Each word's first attempt, in session order, and the totals."""

    words: list[SummaryWord]
    word_count: int
    correct_count: int


class EndResponse(BaseModel):
    type: Literal["end"] = "end"
    summary: SessionSummaryResponse


class AnswerRequest(BaseModel):
    """Exactly one of typed text, a choice index, or "I don't know"."""

    answer: str | None = None
    choice: int | None = None
    dont_know: bool = False

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> Self:
        given = (self.answer is not None) + (self.choice is not None) + self.dont_know
        if given != 1:
            raise ValueError('Send exactly one of "answer", "choice" or "dont_know": true.')
        return self

    def submitted(self) -> SubmittedAnswer:
        if self.answer is not None:
            return TypedAnswer(self.answer)
        if self.choice is not None:
            return ChoiceAnswer(self.choice)
        return DontKnowAnswer()


class AnswerResponse(BaseModel):
    """The verdict, the word, and its statistics before and after (null if it was deleted)."""

    correct: bool
    korean: str
    translations: list[str]
    correct_option: str | None
    scored: bool
    statistics_before: WordStatistics | None
    statistics_after: WordStatistics | None


@dataclass
class VocabSession:
    """One session in progress: its plan, and what it has handed out.

    Attributes:
        directions: the directions its questions are drawn from.
        plan: T02's sequencing.
        words: every word at session start, by id, for the summary.
        undelivered: an item the plan handed out whose response failed (synthesis), kept
            so the next call serves the same word instead of skipping it.
        shown_item_id: the item id last handed to the browser, while it stands.
        done: words whose scored question has been answered.
        lock: serialises `next` with itself and with an answer, take to bookkeeping.
    """

    directions: tuple[Direction, ...]
    plan: SessionPlan
    words: dict[int, VocabularyWord]
    undelivered: SessionItem | None = None
    shown_item_id: str | None = None
    done: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class PendingVocabItem:
    """A handed-out presentation or question: `question` is `None` for a presentation.

    `item.word` is the word as it was when the item was built, which is what a presentation
    shows and speaks."""

    session_id: str
    item: SessionItem
    question: VocabQuestion | None


def _sessions(request: Request) -> dict[str, VocabSession]:
    sessions: dict[str, VocabSession] = request.app.state.vocab_sessions
    return sessions


def _items(request: Request) -> dict[str, PendingVocabItem]:
    items: dict[str, PendingVocabItem] = request.app.state.vocab_items
    return items


def _word_store(request: Request) -> WordStore:
    store: WordStore = request.app.state.word_store
    return store


def _audio_cache(request: Request) -> AudioCache:
    cache: AudioCache = request.app.state.audio_cache
    return cache


def _now(request: Request) -> datetime:
    clock: Callable[[], datetime] = request.app.state.clock
    return clock()


@router.post("/sessions", response_model=StartSessionResponse, status_code=201)
def start_session(body: StartSessionRequest, request: Request) -> StartSessionResponse:
    """Start a session over new words (learn) or due words (review); 409 if there is none."""
    store = _word_store(request)
    size = body.size if body.size is not None else _DEFAULT_SIZES[body.kind]
    if body.kind is SessionKind.LEARN:
        words = store.new_words(tag=body.tag, limit=size)
    else:
        words = store.due_words(_now(request), tag=body.tag, limit=size)
    if not words:
        tagged = "" if body.tag is None else f" tagged {body.tag!r}"
        raise HTTPException(status_code=409, detail=f"There is nothing to {body.kind}{tagged}.")

    directions = tuple(dict.fromkeys(body.directions))
    session = VocabSession(
        directions=directions,
        plan=SessionPlan(body.kind, words),
        words={word.id: word for word in words},
    )
    session_id = store_pending(_sessions(request), session)
    return StartSessionResponse(
        session_id=session_id,
        kind=body.kind,
        word_count=len(words),
        directions=list(directions),
    )


@router.post("/sessions/{session_id}/next")
def next_item(
    session_id: str, request: Request
) -> PresentationResponse | QuestionResponse | EndResponse:
    """The next presentation or question, the one still pending, or the end."""
    sessions = _sessions(request)
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}.")
    items = _items(request)

    with session.lock:
        shown = session.shown_item_id
        pending = None if shown is None else items.get(shown)
        if shown is not None and pending is not None and pending.question is not None:
            return _item_response(request, session, shown, pending)
        if shown is not None:
            items.pop(shown, None)  # a presentation seen: the session moves on
            session.shown_item_id = None

        item = session.undelivered or session.plan.next_item()
        if item is None:
            sessions.pop(session_id, None)
            return EndResponse(summary=_summary(session))
        session.undelivered = item

        pending = _prepare(request, session_id, session, item)
        item_id = store_pending(items, pending)
        session.undelivered = None
        session.shown_item_id = item_id
        return _item_response(request, session, item_id, pending)


@router.get("/items/{item_id}/audio", name=_AUDIO_ROUTE_NAME)
def get_item_audio(item_id: str, request: Request) -> FileResponse:
    """The WAV of a presentation or a voice question, without consuming it."""
    pending = get_pending_or_404(_items(request), item_id)
    text = _speech(pending)
    if text is None:
        raise HTTPException(status_code=404, detail="This question has no audio.")
    return FileResponse(synthesise_or_502(_audio_cache(request), text), media_type="audio/wav")


@router.post("/items/{item_id}/answer", response_model=AnswerResponse)
def submit_answer(item_id: str, body: AnswerRequest, request: Request) -> AnswerResponse:
    """Judge an answer, consuming the question; score it if it is the word's scored one."""
    items = _items(request)
    pending = get_pending_or_404(items, item_id)
    if pending.question is None:
        raise HTTPException(status_code=422, detail="A presentation cannot be answered.")
    try:
        judgement = judge_answer(pending.question, body.submitted())
    except MalformedAnswerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # A session only ends once its every question is answered, so it holds this one's.
    session = _sessions(request)[pending.session_id]

    with session.lock:
        take_pending_or_404(items, item_id)
        scored, before, after = _score(request, pending, pending.question, judgement)
        session.plan.record_answer(pending.item.number, correct=judgement.correct)
        if pending.item.scored:
            session.done += 1
        if session.shown_item_id == item_id:
            session.shown_item_id = None

    return AnswerResponse(
        correct=judgement.correct,
        korean=judgement.korean,
        translations=list(judgement.translations),
        correct_option=judgement.correct_option,
        scored=scored,
        statistics_before=before,
        statistics_after=after,
    )


def _prepare(
    request: Request, session_id: str, session: VocabSession, item: SessionItem
) -> PendingVocabItem:
    """Build the item's question from the word as it is now, and synthesise its audio.

    The word is read again because its memory may have moved since the session started (a
    practice question after a lapse is asked by choice again); a word deleted meanwhile is
    asked from the session's snapshot, then judged but not scored. Synthesis raises the 502
    before anything is stored.
    """
    store = _word_store(request)
    word = store.get_word(item.word.id) or item.word
    question = None
    if item.kind is ItemKind.QUESTION:
        question = build_question(
            word, draw_direction(session.directions), candidates=store.list_words()
        )
    pending = PendingVocabItem(
        session_id=session_id, item=dataclasses.replace(item, word=word), question=question
    )
    text = _speech(pending)
    if text is not None:
        synthesise_or_502(_audio_cache(request), text)
    return pending


def _item_response(
    request: Request, session: VocabSession, item_id: str, pending: PendingVocabItem
) -> PresentationResponse | QuestionResponse:
    progress = Progress(done=session.done, total=len(session.words))
    audio_url = None
    if _speech(pending) is not None:
        audio_url = str(request.app.url_path_for(_AUDIO_ROUTE_NAME, item_id=item_id))
    question = pending.question
    if question is None:
        word = pending.item.word
        return PresentationResponse(
            item_id=item_id,
            korean=word.korean,
            translations=list(word.translations),
            audio_url=str(audio_url),
            progress=progress,
        )
    return QuestionResponse(
        item_id=item_id,
        direction=question.direction,
        mode=question.mode.value,
        prompt=question.prompt,
        audio_url=audio_url,
        options=list(question.options) if question.choices is not None else None,
        scored=pending.item.scored,
        progress=progress,
    )


def _speech(pending: PendingVocabItem) -> str | None:
    """What an item speaks: a presentation its word, a question its speech (voice only)."""
    if pending.question is None:
        return pending.item.word.korean
    return pending.question.speech


def _score(
    request: Request,
    pending: PendingVocabItem,
    question: VocabQuestion,
    judgement: VocabJudgement,
) -> tuple[bool, WordStatistics | None, WordStatistics | None]:
    """Grade and record the answer if it is the word's scored one; whether it was, and the
    word's statistics before and after (the same for practice, `None` for a deleted word)."""
    store = _word_store(request)
    at = _now(request)
    word = store.get_word(question.word_id)
    if word is None:
        return False, None, None
    before = statistics(word.memory, at)
    if not pending.item.scored:
        return False, before, before

    grade = grade_for(correct=judgement.correct, mode=question.mode)
    state, record = apply_grade(word.memory, grade, at)
    context = AnswerContext(
        direction=question.direction, mode=question.mode, correct=judgement.correct
    )
    if not store.record_answer(word.id, state, record, context):
        return False, None, None
    return True, before, statistics(state, at)


def _summary(session: VocabSession) -> SessionSummaryResponse:
    summary = session.plan.summary()
    words = []
    for result in summary.results:
        word = session.words[result.word_id]
        words.append(
            SummaryWord(
                korean=word.korean,
                translations=list(word.translations),
                correct=result.correct,
            )
        )
    return SessionSummaryResponse(
        words=words, word_count=summary.word_count, correct_count=summary.correct_count
    )
