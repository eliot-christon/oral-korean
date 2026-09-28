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
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from oral_korean.exercises.vocab import AnswerMode, Direction
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
    WordStatistics,
    aggregate_statistics,
    score,
    seed,
    statistics,
)
from oral_korean.storage.words import DuplicateWordError, HistoryRow, WordStore

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


class WordResponse(BaseModel):
    """A stored word and its statistics, read at the clock's instant: `statistics` over the
    word as a whole (the four directions' memories aggregated), `direction_statistics` for
    each direction, all four always present. Both are `srs.WordStatistics` values: pydantic
    serialises the frozen dataclass as is."""

    id: int
    korean: str
    translations: list[str]
    tags: list[str]
    familiarity: Familiarity
    added_at: datetime
    statistics: WordStatistics
    direction_statistics: dict[Direction, WordStatistics]


class HistoryEntry(BaseModel):
    """A seed or an answer, and what followed it. `recall_before` is a whole percent, like
    a word's `recall`, and null for a seed: the word had no memory before it. `direction`,
    `mode` and `correct` say how an answer was asked and how it went; null for a seed."""

    reviewed_at: datetime
    grade: Grade
    is_seed: bool
    recall_before: int | None
    stability: float
    difficulty: float
    next_review: datetime
    direction: Direction | None
    mode: AnswerMode | None
    correct: bool | None


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


class TagMatch(StrEnum):
    """Whether a listed word carries any of the included tags, or all of them."""

    ANY = "any"
    ALL = "all"


class WordSort(StrEnum):
    """What the list is sorted by: the headline score, the adding order, the next review, or
    the Korean by code point (dictionary order, for modern Hangul syllables)."""

    SCORE = "score"
    ADDED = "added"
    NEXT_REVIEW = "next_review"
    KOREAN = "korean"


class SortOrder(StrEnum):
    """The direction of the sort."""

    ASC = "asc"
    DESC = "desc"


class WordListQuery(BaseModel):
    """Which words to list and in what order. With nothing given, every word, in the order
    they were added. `tag` and `exclude` repeat; a tag stored nowhere matches nothing."""

    tag: list[str] = Field(default_factory=list)
    match: TagMatch = TagMatch.ANY
    exclude: list[str] = Field(default_factory=list)
    sort: WordSort = WordSort.ADDED
    order: SortOrder = SortOrder.ASC


class WordListResponse(BaseModel):
    """The listed words, in the order asked, and their summary."""

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


def _word_response(word: VocabularyWord, at: datetime) -> WordResponse:
    return WordResponse(
        id=word.id,
        korean=word.korean,
        translations=list(word.translations),
        tags=list(word.tags),
        familiarity=word.familiarity,
        added_at=word.added_at,
        statistics=_word_statistics(word, at),
        direction_statistics={
            direction: statistics(memory, at) for direction, memory in word.memories.items()
        },
    )


def _word_statistics(word: VocabularyWord, at: datetime) -> WordStatistics:
    """The word's headline statistics: its four directions' memories aggregated."""
    return aggregate_statistics([word.memories[direction] for direction in Direction], at)


def _history_entry(row: HistoryRow) -> HistoryEntry:
    record, answer = row.record, row.answer
    recall_before = None if record.recall_before is None else round(100 * record.recall_before)
    return HistoryEntry(
        reviewed_at=record.reviewed_at,
        grade=record.grade,
        is_seed=record.is_seed,
        recall_before=recall_before,
        stability=record.stability,
        difficulty=record.difficulty,
        next_review=record.next_review,
        direction=None if answer is None else answer.direction,
        mode=None if answer is None else answer.mode,
        correct=None if answer is None else answer.correct,
    )


def _summary(all_statistics: Sequence[WordStatistics]) -> VocabularySummary:
    scores = [figures.score for figures in all_statistics if figures.score is not None]
    return VocabularySummary(
        total=len(all_statistics),
        new=sum(figures.phase is Phase.NEW for figures in all_statistics),
        due=sum(figures.due for figures in all_statistics),
        average_score=round(sum(scores) / len(scores)) if scores else None,
    )


def _sort_key(
    word: VocabularyWord, figures: WordStatistics, sort: WordSort
) -> int | str | datetime | None:
    """What `sort` orders `word` by; `None` for a word with no score or no next review."""
    match sort:
        case WordSort.SCORE:
            return figures.score
        case WordSort.ADDED:
            # Ids follow the adding order, and tell apart words added in one batch.
            return word.id
        case WordSort.NEXT_REVIEW:
            return figures.next_review
        case WordSort.KOREAN:
            return word.korean


def _sorted(
    listed: Sequence[tuple[VocabularyWord, WordStatistics]], sort: WordSort, order: SortOrder
) -> list[tuple[VocabularyWord, WordStatistics]]:
    """`listed`, in adding order, sorted by `sort` in `order`: ties keep the adding order and
    a word without a value comes last, in either order."""
    keyed = [(_sort_key(word, figures, sort), (word, figures)) for word, figures in listed]
    valued = [(key, item) for key, item in keyed if key is not None]
    # sorted() is stable, and stays so with reverse=True: tied words keep their order.
    valued.sort(key=lambda pair: pair[0], reverse=order is SortOrder.DESC)
    return [item for _, item in valued] + [item for key, item in keyed if key is None]


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
    request: Request, query: Annotated[WordListQuery, Query()]
) -> WordListResponse:
    """The words the query selects, in the order it asks, with statistics and a summary of
    those words alone.

    Raises:
        HTTPException: 422 when a tag is both included and excluded.
    """
    both = sorted(set(query.tag) & set(query.exclude))
    if both:
        raise HTTPException(
            status_code=422,
            detail=f"A tag cannot be both included and excluded: {', '.join(both)}.",
        )
    at = _now(request)
    words = _word_store(request).list_words(
        tags=query.tag, match_all=query.match is TagMatch.ALL, exclude=query.exclude
    )
    listed = _sorted(
        [(word, _word_statistics(word, at)) for word in words], query.sort, query.order
    )
    return WordListResponse(
        words=[_word_response(word, at) for word, _ in listed],
        summary=_summary([figures for _, figures in listed]),
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
        history=[_history_entry(row) for row in store.history(word_id)],
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
