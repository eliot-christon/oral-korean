"""HTTP routes for the number-recognition exercise.

Thin over T02 and T03: this module draws no numbers and judges no answers itself, it only
translates `exercises.numbers` and `tts.cache` into requests and responses. The pending
question store and the audio cache both live on `request.app.state`, set up by
`create_app`, so two apps built by the factory never share a question.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from oral_korean.api.audio import synthesise_or_502
from oral_korean.api.pending import get_pending_or_404, store_pending
from oral_korean.exercises.numbers import (
    InvalidRangeError,
    NumberQuestion,
    Verdict,
    draw_number_question,
    judge_answer,
)
from oral_korean.korean.numerals import DEFAULT_NUMERAL_SYSTEM, NumeralSystem, supported_range
from oral_korean.tts.cache import AudioCache

router = APIRouter(prefix="/exercises/numbers")

_AUDIO_ROUTE_NAME = "numbers_question_audio"


class NumeralSystemInfo(BaseModel):
    """One entry of the systems catalogue: a system and the range it supports."""

    system: NumeralSystem
    minimum: int
    maximum: int


class SystemsResponse(BaseModel):
    """The full systems catalogue, for the frontend to build its selector from."""

    systems: list[NumeralSystemInfo]


class CreateQuestionRequest(BaseModel):
    """A request to draw a question, all fields optional."""

    system: NumeralSystem = DEFAULT_NUMERAL_SYSTEM
    minimum: int | None = None
    maximum: int | None = None


class CreateQuestionResponse(BaseModel):
    """What the browser learns about a freshly drawn question - never the answer."""

    question_id: str
    audio_url: str
    system: NumeralSystem


class AnswerRequest(BaseModel):
    """A typed answer, exactly as submitted - not length-constrained, so an empty string
    still reaches `judge_answer`, the one place that gets to call it not-a-number."""

    answer: str


class AnswerResponse(BaseModel):
    """The verdict on a submitted answer, with the expected number and its Korean text."""

    verdict: Verdict
    expected_number: int
    text: str


def _question_store(request: Request) -> dict[str, NumberQuestion]:
    """The pending-question store for this app instance."""
    store: dict[str, NumberQuestion] = request.app.state.number_questions
    return store


def _audio_cache(request: Request) -> AudioCache:
    """The audio cache for this app instance."""
    cache: AudioCache = request.app.state.audio_cache
    return cache


@router.get("/systems", response_model=SystemsResponse)
def list_systems() -> SystemsResponse:
    """Report every numeral system and the range it supports."""
    return SystemsResponse(
        systems=[
            NumeralSystemInfo(
                system=system,
                minimum=supported_range(system).minimum,
                maximum=supported_range(system).maximum,
            )
            for system in NumeralSystem
        ]
    )


@router.post("/questions", response_model=CreateQuestionResponse)
def create_question(body: CreateQuestionRequest, request: Request) -> CreateQuestionResponse:
    """Draw a question, synthesise its audio, store it as pending, and return its id."""
    try:
        question = draw_number_question(body.system, minimum=body.minimum, maximum=body.maximum)
    except InvalidRangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    synthesise_or_502(_audio_cache(request), question.text)

    question_id = store_pending(_question_store(request), question)
    audio_url = str(request.app.url_path_for(_AUDIO_ROUTE_NAME, question_id=question_id))
    return CreateQuestionResponse(
        question_id=question_id, audio_url=audio_url, system=question.system
    )


@router.get("/questions/{question_id}/audio", name=_AUDIO_ROUTE_NAME)
def get_question_audio(question_id: str, request: Request) -> FileResponse:
    """Serve the WAV for `question_id`, synthesising it first on a cache miss."""
    question = get_pending_or_404(_question_store(request), question_id)
    audio_path = synthesise_or_502(_audio_cache(request), question.text)
    return FileResponse(audio_path, media_type="audio/wav")


@router.post("/questions/{question_id}/answer", response_model=AnswerResponse)
def submit_answer(question_id: str, body: AnswerRequest, request: Request) -> AnswerResponse:
    """Judge `body.answer` against the pending question, without consuming it."""
    question = get_pending_or_404(_question_store(request), question_id)
    judgement = judge_answer(question, body.answer)
    return AnswerResponse(
        verdict=judgement.verdict,
        expected_number=judgement.expected_number,
        text=judgement.text,
    )
