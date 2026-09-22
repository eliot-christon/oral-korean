"""HTTP routes for the vocabulary: add, edit, delete and read words with their FSRS statistics.

Thin over vocab-core T01 to T04: this module splits no translation, normalises no Korean,
computes no memory and writes no SQL. `exercises.vocab_words` turns what the user typed into
drafts, `srs.memory` seeds them and reads their statistics, and `storage.words` keeps them.
The word store and the clock both live on `request.app.state`, set up by `create_app`, so two
apps built by the factory never share a word and every statistic is read at an instant a test
can choose.

Two refusal shapes, deliberately distinct: a single entry is refused with a **string**
`detail`, as the numbers routes surface `InvalidRangeError`, so the frontend's `errorDetail`
shows it; a pasted batch is refused with `{"errors": [{"line", "message"}, ...]}`, every
problem at once, which pydantic's own validation list (a list under `detail`) cannot be
mistaken for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from oral_korean.exercises.vocab_words import (
    EntryProblem,
    VocabularyWord,
    WordDraft,
    WordEntryError,
    make_draft,
    parse_pasted_list,
)
from oral_korean.srs.memory import (
    Familiarity,
    Grade,
    Phase,
    ReviewRecord,
    WordStatistics,
    score,
    seed,
    statistics,
)
from oral_korean.storage.words import DuplicateWordError, WordStore

router = APIRouter(prefix="/vocab")


class AddWordRequest(BaseModel):
    """One word typed in the add form; the translations exactly as typed (`"house; home"`)."""

    korean: str
    translations: str
    tags: list[str] = Field(default_factory=list)
    familiarity: Familiarity = Familiarity.NEW


class AddPastedWordsRequest(BaseModel):
    """A pasted list, one word per line; the tags and familiarity apply to every word."""

    text: str
    tags: list[str] = Field(default_factory=list)
    familiarity: Familiarity = Familiarity.NEW


class EditWordRequest(BaseModel):
    """A word's new Korean, translations (as typed) and tags. Familiarity cannot be edited."""

    korean: str
    translations: str
    tags: list[str] = Field(default_factory=list)


class WordStatisticsResponse(BaseModel):
    """Everything FSRS knows about a word at the clock's instant; see `srs.WordStatistics`."""

    model_config = ConfigDict(from_attributes=True)

    score: int | None
    recall: int | None
    phase: Phase
    stability: float | None
    difficulty: float | None
    next_review: datetime | None
    last_review: datetime | None
    due: bool
    review_count: int
    lapse_count: int


class WordResponse(BaseModel):
    """A stored word and its statistics."""

    id: int
    korean: str
    translations: list[str]
    tags: list[str]
    familiarity: Familiarity
    added_at: datetime
    statistics: WordStatisticsResponse


class HistoryEntry(BaseModel):
    """A seed or an answer, and what followed it. `recall_before` is a whole percent, like
    a word's `recall`, and null for a seed: the word had no memory before it."""

    reviewed_at: datetime
    grade: Grade
    is_seed: bool
    recall_before: int | None
    stability: float
    difficulty: float
    next_review: datetime


class WordDetailResponse(WordResponse):
    """A word, its statistics and its history, oldest first."""

    history: list[HistoryEntry]


class VocabularySummary(BaseModel):
    """The listed words at a glance. `average_score` counts only words with a score, and is
    null when every listed word is new."""

    total: int
    new: int
    due: int
    average_score: int | None


class WordListResponse(BaseModel):
    """The listed words, in the order they were added, and their summary."""

    words: list[WordResponse]
    summary: VocabularySummary


class AddedWordsResponse(BaseModel):
    """The words a paste added, in the order of their lines."""

    words: list[WordResponse]


class TagCountResponse(BaseModel):
    """A tag and how many words carry it."""

    tag: str
    count: int


class TagsResponse(BaseModel):
    """Every tag in use, sorted."""

    tags: list[TagCountResponse]


class FamiliarityLevel(BaseModel):
    """What adding a word at one familiarity level seeds. Every figure is null for `new`,
    which seeds nothing; `first_review_in_days` is the unfuzzed delay, which the real
    seeding may move by a day or two once it is several days long."""

    familiarity: Familiarity
    grade: Grade | None
    score: int | None
    stability: float | None
    first_review_in_days: int | None


class FamiliarityResponse(BaseModel):
    """Every familiarity level, from `new` to `very_well`."""

    levels: list[FamiliarityLevel]


def _word_store(request: Request) -> WordStore:
    """The word store for this app instance."""
    store: WordStore = request.app.state.word_store
    return store


def _now(request: Request) -> datetime:
    """The current instant, from this app instance's clock."""
    clock: Callable[[], datetime] = request.app.state.clock
    return clock()


def _not_found(word_id: int) -> HTTPException:
    """The 404 every unknown-id route shares."""
    return HTTPException(status_code=404, detail=f"No word with id {word_id}.")


def _batch_refusal(problems: Sequence[EntryProblem]) -> HTTPException:
    """The 422 of a refused paste: every problem, with its line or none."""
    errors = [{"line": problem.line, "message": problem.message} for problem in problems]
    return HTTPException(status_code=422, detail={"errors": errors})


def _add(
    request: Request, drafts: Sequence[WordDraft], at: datetime
) -> tuple[VocabularyWord, ...]:
    """Store `drafts`, each with the memory `srs/` seeds for its familiarity at `at`."""
    entries = [(draft, seed(draft.familiarity, at)) for draft in drafts]
    return _word_store(request).add_words(entries, at)


def _statistics_response(word: VocabularyWord, at: datetime) -> WordStatisticsResponse:
    return WordStatisticsResponse.model_validate(statistics(word.memory, at))


def _word_response(word: VocabularyWord, at: datetime) -> WordResponse:
    return WordResponse(
        id=word.id,
        korean=word.korean,
        translations=list(word.translations),
        tags=list(word.tags),
        familiarity=word.familiarity,
        added_at=word.added_at,
        statistics=_statistics_response(word, at),
    )


def _history_entry(record: ReviewRecord) -> HistoryEntry:
    recall_before = None if record.recall_before is None else round(100 * record.recall_before)
    return HistoryEntry(
        reviewed_at=record.reviewed_at,
        grade=record.grade,
        is_seed=record.is_seed,
        recall_before=recall_before,
        stability=record.stability,
        difficulty=record.difficulty,
        next_review=record.next_review,
    )


def _summary(all_statistics: Sequence[WordStatistics]) -> VocabularySummary:
    scores = [figures.score for figures in all_statistics if figures.score is not None]
    return VocabularySummary(
        total=len(all_statistics),
        new=sum(figures.phase is Phase.NEW for figures in all_statistics),
        due=sum(figures.due for figures in all_statistics),
        average_score=round(sum(scores) / len(scores)) if scores else None,
    )


def _familiarity_level(familiarity: Familiarity, at: datetime) -> FamiliarityLevel:
    seeded = seed(familiarity, at, fuzzing=False)
    if seeded is None:
        return FamiliarityLevel(
            familiarity=familiarity, grade=None, score=None, stability=None,
            first_review_in_days=None,
        )
    state, record = seeded
    return FamiliarityLevel(
        familiarity=familiarity,
        grade=record.grade,
        score=score(state),
        stability=state.stability,
        first_review_in_days=(state.next_review - at).days,
    )


@router.get("/words", response_model=WordListResponse)
def list_words(
    request: Request, tag: Annotated[str | None, Query()] = None
) -> WordListResponse:
    """Every word, or every word carrying `tag`, with statistics and a summary."""
    at = _now(request)
    words = _word_store(request).list_words(tag=tag)
    responses = [_word_response(word, at) for word in words]
    return WordListResponse(
        words=responses,
        summary=_summary([statistics(word.memory, at) for word in words]),
    )


@router.get("/words/{word_id}", response_model=WordDetailResponse)
def get_word(word_id: int, request: Request) -> WordDetailResponse:
    """One word, its statistics and its history."""
    store = _word_store(request)
    word = store.get_word(word_id)
    if word is None:
        raise _not_found(word_id)
    return WordDetailResponse(
        **_word_response(word, _now(request)).model_dump(),
        history=[_history_entry(record) for record in store.history(word_id)],
    )


@router.post("/words", response_model=WordResponse, status_code=201)
def add_word(body: AddWordRequest, request: Request) -> WordResponse:
    """Add one word, seeded from its familiarity."""
    try:
        draft = make_draft(body.korean, body.translations, body.tags, body.familiarity)
    except WordEntryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    at = _now(request)
    try:
        (word,) = _add(request, [draft], at)
    except DuplicateWordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _word_response(word, at)


@router.post("/words/batch", response_model=AddedWordsResponse, status_code=201)
def add_pasted_words(body: AddPastedWordsRequest, request: Request) -> AddedWordsResponse:
    """Add every word of a pasted list, or none: a refusal lists every problem by line."""
    stored = [word.korean for word in _word_store(request).list_words()]
    try:
        drafts = parse_pasted_list(body.text, body.tags, body.familiarity, stored=stored)
    except WordEntryError as exc:
        raise _batch_refusal(exc.problems) from exc
    at = _now(request)
    try:
        words = _add(request, drafts, at)
    except DuplicateWordError as exc:
        # Only a word stored between the read above and this write gets here.
        raise _batch_refusal([EntryProblem(None, str(exc))]) from exc
    return AddedWordsResponse(words=[_word_response(word, at) for word in words])


@router.put("/words/{word_id}", response_model=WordResponse)
def edit_word(word_id: int, body: EditWordRequest, request: Request) -> WordResponse:
    """Replace a word's Korean, translations and tags; its memory and history stay."""
    store = _word_store(request)
    word = store.get_word(word_id)
    if word is None:
        raise _not_found(word_id)
    try:
        draft = make_draft(body.korean, body.translations, body.tags, word.familiarity)
    except WordEntryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        updated = store.update_word(word_id, draft.korean, draft.translations, draft.tags)
    except DuplicateWordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise _not_found(word_id)
    return _word_response(updated, _now(request))


@router.delete("/words/{word_id}", status_code=204)
def delete_word(word_id: int, request: Request) -> Response:
    """Delete a word with its history."""
    if not _word_store(request).delete_word(word_id):
        raise _not_found(word_id)
    return Response(status_code=204)


@router.get("/tags", response_model=TagsResponse)
def list_tags(request: Request) -> TagsResponse:
    """Every tag in use with its word count, sorted by tag."""
    return TagsResponse(
        tags=[
            TagCountResponse(tag=count.tag, count=count.count)
            for count in _word_store(request).tag_counts()
        ]
    )


@router.get("/familiarity", response_model=FamiliarityResponse)
def list_familiarity_levels(request: Request) -> FamiliarityResponse:
    """What each familiarity level seeds, computed through `srs/` at the clock's instant."""
    at = _now(request)
    return FamiliarityResponse(
        levels=[_familiarity_level(familiarity, at) for familiarity in Familiarity]
    )
