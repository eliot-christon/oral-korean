"""Tests for the HTTP layer of the clock exercise (time-exercise T03).

Framing-mode note: the routes do not exist yet. These tests pin the contract of
`oral_korean.api.routes.time_of_day`, mounted under `/api/exercises/time`:

- `GET /levels` -> `{"levels": [{"level": str, "minute_step": int}, ...], "default": str}`,
  one entry per `Level` member in its order, read from `exercises.time_of_day`.
- `POST /questions`, body `{"level"?: str}` -> exactly `question_id`, `audio_url`, `level`,
  `minute_step`. An unknown level is pydantic's own `422`, before any drawing or synthesis.
  The audio is synthesised eagerly; a failure is a `502` with the shared, text-free detail,
  and nothing is stored.
- `GET /questions/{question_id}/audio` -> the WAV; `audio_url` is exactly this path.
- `POST /questions/{question_id}/answer`, body `{"period", "hour", "minute"}` validated
  strictly (a strict int 1-12, a strict int 0-59, `period` exactly `"am"` or `"pm"`):
  `"3"`, `3.5`, `3.0` and `true` are all `422`, not coerced. The response is
  `{"verdict", "expected": {"period", "hour", "minute"}, "text"}`. Answering never consumes
  the question; an unknown id is `404`.
- The pending store is `app.state.time_questions: dict[str, TimeQuestion]`, created by
  `create_app`, so two apps never share a question.

The expected selection is always obtained from `judge_selection` (tested on its own in
`test_exercises_time_of_day.py`), never converted from 24 to 12 hours here: that conversion
lives in exactly one place, and a copy of it in a test would survive its removal.

Offline: every test wires a `FakeSpeechEngine` through `tests/conftest.py`'s harness, except
the last, which needs the real MeloTTS and is skipped unless `ORAL_KOREAN_TTS_E2E` is set.
"""

from __future__ import annotations

import os
import unicodedata
import wave
from pathlib import Path
from typing import Final

import pytest
from conftest import FakeSpeechEngine, NumbersHarness, build_numbers_harness, leaks

from oral_korean.config import AppConfig
from oral_korean.exercises.time_of_day import (
    DEFAULT_LEVEL,
    ClockSelection,
    Level,
    Period,
    TimeQuestion,
    judge_selection,
    minute_step,
)
from oral_korean.tts.base import SpeechSynthesisError
from oral_korean.tts.cache import AudioCache
from oral_korean.tts.melo_engine import MeloSpeechEngine

LEVELS_PATH: Final = "/api/exercises/time/levels"
QUESTIONS_PATH: Final = "/api/exercises/time/questions"
CREATE_KEYS: Final = {"question_id", "audio_url", "level", "minute_step"}
SYNTHESIS_FAILURE_DETAIL: Final = "Could not synthesise audio for this question."
"""The shared detail of `api/audio.py`, named by CLAUDE.md: stated here, not imported
from a private name."""

MISSING: Final = object()
"""Marks a field removed from an answer body, as opposed to one set to `null`."""


def audio_path(question_id: str) -> str:
    return f"{QUESTIONS_PATH}/{question_id}/audio"


def answer_path(question_id: str) -> str:
    return f"{QUESTIONS_PATH}/{question_id}/answer"


def stored_time_question(harness: NumbersHarness, question_id: str) -> TimeQuestion:
    """The pending question the server holds, read from `app.state.time_questions`.

    Straight from the store, because no route may hand the time or its Korean text back
    before an answer is submitted - which is what several tests below check.
    """
    store: dict[str, TimeQuestion] = harness.app.state.time_questions
    return store[question_id]


def time_store_size(harness: NumbersHarness) -> int:
    return len(harness.app.state.time_questions)


def create(harness: NumbersHarness, **body: object) -> dict[str, object]:
    """Create a question that must be accepted; the response body."""
    response = harness.client.post(QUESTIONS_PATH, json=body)
    assert response.status_code == 200, response.text
    created: dict[str, object] = response.json()
    return created


def question_id_of(created: dict[str, object]) -> str:
    question_id = created["question_id"]
    assert isinstance(question_id, str) and question_id
    return question_id


def expected_selection(question: TimeQuestion) -> ClockSelection:
    """The position the exercise module reports as right for `question`."""
    return judge_selection(question, ClockSelection(period=Period.AM, hour=12, minute=0)).expected


def as_body(chosen: ClockSelection) -> dict[str, object]:
    return {"period": chosen.period.value, "hour": chosen.hour, "minute": chosen.minute}


def right_body(question: TimeQuestion) -> dict[str, object]:
    return as_body(expected_selection(question))


def other_period_body(question: TimeQuestion) -> dict[str, object]:
    expected = expected_selection(question)
    flipped = Period.PM if expected.period is Period.AM else Period.AM
    return as_body(ClockSelection(period=flipped, hour=expected.hour, minute=expected.minute))


def has_hangul(text: str) -> bool:
    return any(unicodedata.name(character, "").startswith("HANGUL") for character in text)


# ---------------------------------------------------------------------------------
# The levels catalogue
# ---------------------------------------------------------------------------------


def test_levels_catalogue_matches_the_exercise_module(numbers_harness: NumbersHarness) -> None:
    """Every level with its step, in order, and the default: read from the module, so the
    frontend never hardcodes a step and a second copy here cannot drift."""
    response = numbers_harness.client.get(LEVELS_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "levels": [{"level": level.value, "minute_step": minute_step(level)} for level in Level],
        "default": DEFAULT_LEVEL.value,
    }


# ---------------------------------------------------------------------------------
# Creating questions
# ---------------------------------------------------------------------------------


def test_an_empty_request_creates_a_five_minute_question(numbers_harness: NumbersHarness) -> None:
    """No level given: the default, and the response carries exactly four keys."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CREATE_KEYS
    assert body["level"] == "five_minutes"
    assert body["minute_step"] == 5
    question_id = question_id_of(body)
    assert body["audio_url"] == audio_path(question_id)
    assert stored_time_question(numbers_harness, question_id).level is Level.FIVE_MINUTES


@pytest.mark.parametrize("level", list(Level), ids=[level.value for level in Level])
def test_each_level_is_accepted_and_reports_its_step(
    level: Level, numbers_harness: NumbersHarness
) -> None:
    body = create(numbers_harness, level=level.value)

    assert set(body) == CREATE_KEYS
    assert body["level"] == level.value
    assert body["minute_step"] == minute_step(level)
    assert stored_time_question(numbers_harness, question_id_of(body)).level is level


def test_a_half_hour_question_is_drawn_on_the_half_hour(numbers_harness: NumbersHarness) -> None:
    """Repeated, because a level ignored by the route draws on its grid by luck some of the
    time: 20 draws at five minutes land on 0 or 30 about one time in 10^21."""
    for _ in range(20):
        body = create(numbers_harness, level="half_hour")

        assert body["minute_step"] == 30
        question = stored_time_question(numbers_harness, question_id_of(body))
        assert question.moment.minute in {0, 30}


@pytest.mark.parametrize("level", list(Level), ids=[level.value for level in Level])
def test_the_create_response_never_reveals_the_time(
    level: Level, numbers_harness: NumbersHarness
) -> None:
    """Neither the Korean text, nor either period word, nor any Hangul at all: the browser
    learns the time only once it has submitted a position."""
    for _ in range(10):
        body = create(numbers_harness, level=level.value)
        question_id = question_id_of(body)
        question = stored_time_question(numbers_harness, question_id)

        assert not leaks(body, question_id, question.text)
        assert not leaks(body, question_id, "오전")
        assert not leaks(body, question_id, "오후")
        assert not has_hangul(str(body))


@pytest.mark.parametrize(
    "level",
    ["quarter_hour", "", "FIVE_MINUTES", " five_minutes", 5, None],
    ids=["unknown", "empty", "upper-case", "padded", "a-number", "null"],
)
def test_an_unknown_level_is_422_before_anything_happens(
    level: object, numbers_harness: NumbersHarness
) -> None:
    """Rejected, never replaced by the default: nothing drawn, nothing synthesised, nothing
    stored. Pydantic's own validation error, a list under `detail`."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"level": level})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert numbers_harness.engine.call_count == 0
    assert time_store_size(numbers_harness) == 0


def test_the_engine_is_asked_for_the_stored_text_once_eagerly(
    numbers_harness: NumbersHarness,
) -> None:
    """Synthesised at creation, exactly the stored text, and in Hangul only: a digit would be
    read by the engine's own normaliser, in whichever numeral system it likes."""
    body = create(numbers_harness)
    question = stored_time_question(numbers_harness, question_id_of(body))

    assert [call.text for call in numbers_harness.engine.calls] == [question.text]
    assert not any(character in "0123456789" for character in question.text)


@pytest.mark.parametrize(
    "engine",
    [
        FakeSpeechEngine(error=SpeechSynthesisError("boom")),
        FakeSpeechEngine(behaviour="writes_nothing"),
    ],
    ids=["engine_raises", "engine_writes_no_audio"],
)
def test_a_synthesis_failure_on_create_is_502_naming_nothing_and_storing_nothing(
    engine: FakeSpeechEngine, tmp_path: Path
) -> None:
    """A question whose audio cannot be served is never pending, and the failure detail is
    the shared fixed message: the cache's own error names the text it failed to speak."""
    harness = build_numbers_harness(tmp_path, engine=engine)

    response = harness.client.post(QUESTIONS_PATH, json={})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail == SYNTHESIS_FAILURE_DETAIL
    assert engine.calls, "the engine was never asked, so nothing was tested"
    assert engine.calls[0].text not in response.text
    assert not has_hangul(response.text)
    assert time_store_size(harness) == 0


def test_two_questions_get_distinct_ids_and_both_stay_answerable(
    numbers_harness: NumbersHarness,
) -> None:
    first = question_id_of(create(numbers_harness))
    second = question_id_of(create(numbers_harness))

    assert first != second
    for question_id in (first, second):
        question = stored_time_question(numbers_harness, question_id)
        response = numbers_harness.client.post(
            answer_path(question_id), json=right_body(question)
        )
        assert response.json()["verdict"] == "correct"


# ---------------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------------


def test_fetching_audio_returns_wav_bytes(numbers_harness: NumbersHarness) -> None:
    body = create(numbers_harness)

    response = numbers_harness.client.get(str(body["audio_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")
    assert response.content.startswith(b"RIFF")


def test_fetching_audio_twice_does_not_synthesise_again(numbers_harness: NumbersHarness) -> None:
    """Synthesised once at creation; both fetches are cache hits."""
    body = create(numbers_harness)

    first = numbers_harness.client.get(str(body["audio_url"]))
    second = numbers_harness.client.get(str(body["audio_url"]))

    assert first.status_code == second.status_code == 200
    assert numbers_harness.engine.call_count == 1


def test_audio_for_an_unknown_id_is_404(numbers_harness: NumbersHarness) -> None:
    response = numbers_harness.client.get(audio_path("does-not-exist"))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------------


def test_the_expected_selection_is_judged_correct(numbers_harness: NumbersHarness) -> None:
    question_id = question_id_of(create(numbers_harness))
    question = stored_time_question(numbers_harness, question_id)

    response = numbers_harness.client.post(answer_path(question_id), json=right_body(question))

    assert response.status_code == 200
    assert response.json() == {
        "verdict": "correct",
        "expected": right_body(question),
        "text": question.text,
    }


def test_the_other_period_is_judged_incorrect_and_told_the_answer(
    numbers_harness: NumbersHarness,
) -> None:
    """Right hour, right minute, wrong half of the day: incorrect, and the body names the
    right position in the clock's own shape, with the Korean that was spoken."""
    question_id = question_id_of(create(numbers_harness))
    question = stored_time_question(numbers_harness, question_id)

    response = numbers_harness.client.post(
        answer_path(question_id), json=other_period_body(question)
    )

    assert response.status_code == 200
    assert response.json() == {
        "verdict": "incorrect",
        "expected": right_body(question),
        "text": question.text,
    }


def test_an_off_grid_minute_is_judged_not_rejected(numbers_harness: NumbersHarness) -> None:
    """Minute 7 at a half-hour level is a real time that was not asked: incorrect, `200`."""
    question_id = question_id_of(create(numbers_harness, level="half_hour"))
    question = stored_time_question(numbers_harness, question_id)
    off_grid = right_body(question) | {"minute": 7}

    response = numbers_harness.client.post(answer_path(question_id), json=off_grid)

    assert response.status_code == 200
    assert response.json()["verdict"] == "incorrect"


def with_override(body: dict[str, object], field: str, value: object) -> dict[str, object]:
    """`body` with `field` set to `value`, or removed when `value` is `MISSING`."""
    changed = dict(body)
    if value is MISSING:
        del changed[field]
    else:
        changed[field] = value
    return changed


def as_string(value: object) -> object:
    return str(value)


def plus_a_half(value: object) -> object:
    assert isinstance(value, int)
    return value + 0.5


def as_float(value: object) -> object:
    assert isinstance(value, int)
    return float(value)


MALFORMED: Final[list[tuple[str, str, object]]] = [
    ("hour-0", "hour", 0),
    ("hour-13", "hour", 13),
    ("hour-negative", "hour", -1),
    ("minute-60", "minute", 60),
    ("minute-negative", "minute", -1),
    ("hour-fraction", "hour", plus_a_half),
    ("hour-whole-float", "hour", as_float),
    ("hour-as-string", "hour", as_string),
    ("minute-as-string", "minute", as_string),
    ("hour-boolean", "hour", True),
    ("hour-null", "hour", None),
    ("period-upper-case", "period", "AM"),
    ("period-noon", "period", "noon"),
    ("period-empty", "period", ""),
    ("period-korean", "period", "오전"),
    ("period-null", "period", None),
    ("period-missing", "period", MISSING),
    ("hour-missing", "hour", MISSING),
    ("minute-missing", "minute", MISSING),
]
"""Each case changes one field of the right answer, so the only reason to refuse it is the
field under test. A transform (a function) is applied to the right value: "3" for 3, not
an arbitrary "3" that happens to be wrong anyway."""


@pytest.mark.parametrize(
    ("field", "value"),
    [(field, value) for _, field, value in MALFORMED],
    ids=[case_id for case_id, _, _ in MALFORMED],
)
def test_a_malformed_selection_is_422_and_leaves_the_question_answerable(
    field: str, value: object, numbers_harness: NumbersHarness
) -> None:
    """Not a verdict: a request the route refuses before judging. Strict, so `"3"`, `3.0`
    and `true` are not coerced into an hour; `3.5` is not rounded. The refusal names no
    Korean text, and the question still answers `correct` to the right position."""
    question_id = question_id_of(create(numbers_harness))
    question = stored_time_question(numbers_harness, question_id)
    right = right_body(question)
    bad_value = value(right[field]) if callable(value) else value

    response = numbers_harness.client.post(
        answer_path(question_id), json=with_override(right, field, bad_value)
    )

    assert response.status_code == 422
    assert question.text not in response.text
    after = numbers_harness.client.post(answer_path(question_id), json=right)
    assert after.status_code == 200
    assert after.json()["verdict"] == "correct"


def test_an_empty_answer_body_is_422(numbers_harness: NumbersHarness) -> None:
    question_id = question_id_of(create(numbers_harness))

    response = numbers_harness.client.post(answer_path(question_id), json={})

    assert response.status_code == 422
    assert time_store_size(numbers_harness) == 1


def test_answering_an_unknown_id_is_404(numbers_harness: NumbersHarness) -> None:
    response = numbers_harness.client.post(
        answer_path("does-not-exist"), json={"period": "am", "hour": 3, "minute": 0}
    )

    assert response.status_code == 404
    assert isinstance(response.json(), dict)


@pytest.mark.parametrize("which", ["right", "other_period"])
def test_answering_the_same_question_twice_gives_the_same_verdict(
    which: str, numbers_harness: NumbersHarness
) -> None:
    """Answering does not consume, score or change the question."""
    question_id = question_id_of(create(numbers_harness))
    question = stored_time_question(numbers_harness, question_id)
    body = right_body(question) if which == "right" else other_period_body(question)

    first = numbers_harness.client.post(answer_path(question_id), json=body)
    second = numbers_harness.client.post(answer_path(question_id), json=body)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert stored_time_question(numbers_harness, question_id) == question


def test_two_apps_do_not_share_pending_questions(tmp_path: Path) -> None:
    """A new store on the app: a question created on one app is unknown to another."""
    first = build_numbers_harness(tmp_path / "first")
    second = build_numbers_harness(tmp_path / "second")
    body = create(first)
    question_id = question_id_of(body)
    question = stored_time_question(first, question_id)

    audio_response = second.client.get(str(body["audio_url"]))
    answer_response = second.client.post(answer_path(question_id), json=right_body(question))

    assert audio_response.status_code == 404
    assert answer_response.status_code == 404


def test_the_time_store_is_separate_from_the_numbers_store(
    numbers_harness: NumbersHarness,
) -> None:
    """A clock question id means nothing to the numbers exercise, and the reverse."""
    time_id = question_id_of(create(numbers_harness))
    numbers_id = numbers_harness.client.post("/api/exercises/numbers/questions", json={}).json()[
        "question_id"
    ]

    assert time_id not in numbers_harness.app.state.number_questions
    assert numbers_id not in numbers_harness.app.state.time_questions
    wrong_store = numbers_harness.client.post(
        answer_path(numbers_id), json={"period": "am", "hour": 3, "minute": 0}
    )
    assert wrong_store.status_code == 404


# ---------------------------------------------------------------------------------
# The real engine, skipped by default
# ---------------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ORAL_KOREAN_TTS_E2E"),
    reason=(
        "needs the tts extra, the MeloTTS weights and a network; set ORAL_KOREAN_TTS_E2E=1"
        " to run it, which the Linux container can do: see the Dockerfile for why Windows"
        " cannot"
    ),
)
@pytest.mark.parametrize(
    "phrase", ["오후 열두 시 반", "오전 네 시 사십사 분"], ids=["ban", "minutes"]
)
def test_real_melotts_accepts_clock_phrases(phrase: str, tmp_path: Path) -> None:
    """MeloTTS takes the phrases (spaces, 시, 분, 반) and writes a readable WAV. It proves
    acceptance, not pronunciation: listening is the ticket's manual check. The sample rate
    is read from the file, never compared to a constant."""
    config = AppConfig()
    cache = AudioCache(
        MeloSpeechEngine(),
        cache_dir=tmp_path / "audio",
        voice=config.tts_voice,
        speed=config.tts_speed,
    )

    path = cache.get_or_synthesise(phrase)

    assert path.stat().st_size > 0
    with wave.open(str(path), "rb") as handle:
        assert handle.getnframes() > 0
        assert handle.getframerate() > 0
