"""HTTP routes for the clock exercise.

Thin over `exercises.time_of_day`, the way `numbers.py` is thin over `exercises.numbers`:
this module draws no time and judges no selection itself. A malformed selection is refused
here, by the request model, with a `422`; a well-formed one always gets a verdict.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictInt

from oral_korean.api.audio import synthesise_or_502
from oral_korean.api.pending import get_pending_or_404, store_pending
from oral_korean.exercises.time_of_day import (
    DEFAULT_LEVEL,
    ClockSelection,
    Level,
    Period,
    TimeQuestion,
    Verdict,
    draw_time_question,
    judge_selection,
    minute_step,
)
from oral_korean.tts.cache import AudioCache

router = APIRouter(prefix="/exercises/time")

_AUDIO_ROUTE_NAME = "time_question_audio"


class LevelInfo(BaseModel):
    """One entry of the levels catalogue: a level and the step between its minutes."""

    level: Level
    minute_step: int


class LevelsResponse(BaseModel):
    """The levels catalogue and its default, for the frontend to build its selector from."""

    levels: list[LevelInfo]
    default: Level


class CreateQuestionRequest(BaseModel):
    """A request to draw a question; an absent level is the default, an unknown one a 422."""

    level: Level = DEFAULT_LEVEL


class CreateQuestionResponse(BaseModel):
    """What the browser learns about a freshly drawn question - never the time or its text."""

    question_id: str
    audio_url: str
    level: Level
    minute_step: int


class Selection(BaseModel):
    """A 12-hour clock position. Strict: `"3"`, `3.0` and `true` are not an hour."""

    period: Period
    hour: Annotated[StrictInt, Field(ge=1, le=12)]
    minute: Annotated[StrictInt, Field(ge=0, le=59)]


class AnswerResponse(BaseModel):
    """The verdict on a selection, with the expected position and the Korean spoken."""

    verdict: Verdict
    expected: Selection
    text: str


def _question_store(request: Request) -> dict[str, TimeQuestion]:
    """The pending-question store for this app instance."""
    store: dict[str, TimeQuestion] = request.app.state.time_questions
    return store


def _audio_cache(request: Request) -> AudioCache:
    """The audio cache for this app instance."""
    cache: AudioCache = request.app.state.audio_cache
    return cache


@router.get("/levels", response_model=LevelsResponse)
def list_levels() -> LevelsResponse:
    """Report every level, its minute step, and the default."""
    return LevelsResponse(
        levels=[LevelInfo(level=level, minute_step=minute_step(level)) for level in Level],
        default=DEFAULT_LEVEL,
    )


@router.post("/questions", response_model=CreateQuestionResponse)
def create_question(body: CreateQuestionRequest, request: Request) -> CreateQuestionResponse:
    """Draw a question, synthesise its audio, store it as pending, and return its id."""
    question = draw_time_question(body.level)
    synthesise_or_502(_audio_cache(request), question.text)

    question_id = store_pending(_question_store(request), question)
    audio_url = str(request.app.url_path_for(_AUDIO_ROUTE_NAME, question_id=question_id))
    return CreateQuestionResponse(
        question_id=question_id,
        audio_url=audio_url,
        level=question.level,
        minute_step=minute_step(question.level),
    )


@router.get("/questions/{question_id}/audio", name=_AUDIO_ROUTE_NAME)
def get_question_audio(question_id: str, request: Request) -> FileResponse:
    """Serve the WAV for `question_id`, synthesising it first on a cache miss."""
    question = get_pending_or_404(_question_store(request), question_id)
    audio_path = synthesise_or_502(_audio_cache(request), question.text)
    return FileResponse(audio_path, media_type="audio/wav")


@router.post("/questions/{question_id}/answer", response_model=AnswerResponse)
def submit_answer(question_id: str, body: Selection, request: Request) -> AnswerResponse:
    """Judge the submitted clock position against the pending question, without consuming it."""
    question = get_pending_or_404(_question_store(request), question_id)
    judgement = judge_selection(
        question, ClockSelection(period=body.period, hour=body.hour, minute=body.minute)
    )
    expected = judgement.expected
    return AnswerResponse(
        verdict=judgement.verdict,
        expected=Selection(period=expected.period, hour=expected.hour, minute=expected.minute),
        text=judgement.text,
    )
