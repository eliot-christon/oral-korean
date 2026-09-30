"""HTTP routes for the calendar exercise.

Thin over `exercises.dates`, the way `time_of_day.py` is thin over `exercises.time_of_day`:
this module draws no date and judges no selection itself. A selection outside the request
model's bounds is pydantic's `422`; one the exercise refuses (not a real date, or a year
given or missing against the question) is a `422` with the exercise's message, which names
nothing of the answer. A real date always gets a verdict.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictInt

from oral_korean.api.audio import synthesise_or_502
from oral_korean.api.pending import get_pending_or_404, store_pending
from oral_korean.exercises.dates import (
    YEAR_WINDOW,
    DateJudgement,
    DateQuestion,
    DateSelection,
    SelectionError,
    Verdict,
    draw_date_question,
    judge_selection,
)
from oral_korean.tts.cache import AudioCache

router = APIRouter(prefix="/exercises/dates")

_AUDIO_ROUTE_NAME = "date_question_audio"


class YearRangeResponse(BaseModel):
    """The years a dated question is drawn from, for the calendar to bound its year control."""

    minimum: int
    maximum: int


class CreateQuestionResponse(BaseModel):
    """What the browser learns about a freshly drawn question - never the date or its text.

    `asks_year` is the shape of the answer, not its value.
    """

    question_id: str
    audio_url: str
    asks_year: bool


class Selection(BaseModel):
    """A picked day. Strict: `"9"`, `9.0` and `true` are not a month. `year` is required,
    `null` when the question does not ask for it."""

    year: StrictInt | None
    month: Annotated[StrictInt, Field(ge=1, le=12)]
    day: Annotated[StrictInt, Field(ge=1, le=31)]


class AnswerResponse(BaseModel):
    """The verdict on a selection, with the expected date and the Korean spoken."""

    verdict: Verdict
    expected: Selection
    text: str


def _question_store(request: Request) -> dict[str, DateQuestion]:
    """The pending-question store for this app instance."""
    store: dict[str, DateQuestion] = request.app.state.date_questions
    return store


def _audio_cache(request: Request) -> AudioCache:
    """The audio cache for this app instance."""
    cache: AudioCache = request.app.state.audio_cache
    return cache


@router.get("/year-range", response_model=YearRangeResponse)
def get_year_range() -> YearRangeResponse:
    """Report the year window, read from the exercise module."""
    return YearRangeResponse(minimum=YEAR_WINDOW.minimum, maximum=YEAR_WINDOW.maximum)


@router.post("/questions", response_model=CreateQuestionResponse)
def create_question(request: Request) -> CreateQuestionResponse:
    """Draw a question, synthesise its audio, store it as pending, and return its id."""
    question = draw_date_question()
    synthesise_or_502(_audio_cache(request), question.text)

    question_id = store_pending(_question_store(request), question)
    audio_url = str(request.app.url_path_for(_AUDIO_ROUTE_NAME, question_id=question_id))
    return CreateQuestionResponse(
        question_id=question_id, audio_url=audio_url, asks_year=question.asks_year
    )


@router.get("/questions/{question_id}/audio", name=_AUDIO_ROUTE_NAME)
def get_question_audio(question_id: str, request: Request) -> FileResponse:
    """Serve the WAV for `question_id`, synthesising it first on a cache miss."""
    question = get_pending_or_404(_question_store(request), question_id)
    audio_path = synthesise_or_502(_audio_cache(request), question.text)
    return FileResponse(audio_path, media_type="audio/wav")


@router.post("/questions/{question_id}/answer", response_model=AnswerResponse)
def submit_answer(question_id: str, body: Selection, request: Request) -> AnswerResponse:
    """Judge the picked day against the pending question, without consuming it."""
    question = get_pending_or_404(_question_store(request), question_id)
    judgement = _judge(question, body)
    expected = judgement.expected
    return AnswerResponse(
        verdict=judgement.verdict,
        expected=Selection(year=expected.year, month=expected.month, day=expected.day),
        text=judgement.text,
    )


def _judge(question: DateQuestion, body: Selection) -> DateJudgement:
    """The exercise's judgement, or a `422` carrying its refusal."""
    try:
        return judge_selection(question, DateSelection(body.year, body.month, body.day))
    except SelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
