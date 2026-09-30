"""Tests for the HTTP layer of the calendar exercise (date-exercise T02).

The routes, mounted under `/api/exercises/dates`:

- `GET /year-range` -> `{"minimum", "maximum"}`, read from `exercises.dates.YEAR_WINDOW`.
- `POST /questions` (no body) -> exactly `question_id`, `audio_url`, `asks_year`. Synthesised
  eagerly; a failure is the shared text-free `502`, and nothing is stored.
- `GET /questions/{question_id}/audio` -> the WAV.
- `POST /questions/{question_id}/answer`, body `{"year", "month", "day"}` (strict ints, `year`
  required and `null` when not asked) -> `{"verdict", "expected", "text"}`. A malformed
  selection, a year present or absent against the question, or a day that is not real is a
  `422` and leaves the question answerable. Answering never consumes; an unknown id is `404`.

The pending store is `app.state.date_questions`, read directly: no route may hand the date
back before an answer. Offline against the fake engine, except the skip-marked last test.
"""

from __future__ import annotations

import os
import re
import wave
from pathlib import Path
from typing import Final

import pytest
from conftest import FakeSpeechEngine, NumbersHarness, build_numbers_harness, leaks

from oral_korean.config import AppConfig
from oral_korean.exercises.dates import YEAR_WINDOW, DateQuestion, DateSelection
from oral_korean.tts.base import SpeechSynthesisError
from oral_korean.tts.cache import AudioCache
from oral_korean.tts.melo_engine import MeloSpeechEngine

BASE: Final = "/api/exercises/dates"
QUESTIONS: Final = f"{BASE}/questions"
CREATED_KEYS: Final = {"question_id", "audio_url", "asks_year"}
FAILED_SYNTHESIS: Final = "Could not synthesise audio for this question."
"""The shared detail of `api/audio.py`, stated here rather than imported from a private name."""

HANGUL: Final = re.compile(r"[가-힣]")


def date_store(harness: NumbersHarness) -> dict[str, DateQuestion]:
    store: dict[str, DateQuestion] = harness.app.state.date_questions
    return store


def new_question(harness: NumbersHarness) -> tuple[str, dict[str, object]]:
    """Create a question that must be accepted: its id and the response body."""
    response = harness.client.post(QUESTIONS)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    question_id = body["question_id"]
    assert isinstance(question_id, str) and question_id
    return question_id, body


def question_of_kind(harness: NumbersHarness, *, asks_year: bool) -> tuple[str, DateQuestion]:
    """Create questions until one asks (or does not ask) for the year: 1 in 2 each time."""
    for _ in range(200):
        question_id, _body = new_question(harness)
        question = date_store(harness)[question_id]
        if question.asks_year == asks_year:
            return question_id, question
    raise AssertionError("200 draws without the wanted kind of question")


def body_of(selection: DateSelection) -> dict[str, object]:
    return {"year": selection.year, "month": selection.month, "day": selection.day}


def post_answer(harness: NumbersHarness, question_id: str, body: object) -> dict[str, object]:
    response = harness.client.post(f"{QUESTIONS}/{question_id}/answer", json=body)
    assert response.status_code == 200, response.text
    answered: dict[str, object] = response.json()
    return answered


# ---------------------------------------------------------------------------------
# Year range and question creation
# ---------------------------------------------------------------------------------


def test_the_year_range_is_the_exercise_window(numbers_harness: NumbersHarness) -> None:
    response = numbers_harness.client.get(f"{BASE}/year-range")

    assert response.status_code == 200
    assert response.json() == {"minimum": YEAR_WINDOW.minimum, "maximum": YEAR_WINDOW.maximum}


def test_a_created_question_reveals_only_its_id_audio_and_shape(
    numbers_harness: NumbersHarness,
) -> None:
    """Exactly three keys, and neither the Korean text nor any Hangul anywhere in the body."""
    for _ in range(10):
        question_id, body = new_question(numbers_harness)
        question = date_store(numbers_harness)[question_id]

        assert set(body) == CREATED_KEYS
        assert not leaks(body, question_id, question.text)
        assert HANGUL.search(str(body)) is None


def test_asks_year_matches_the_stored_question(numbers_harness: NumbersHarness) -> None:
    """Over 40 questions both kinds appear (missing one has odds of about 2 in 10^12)."""
    seen: set[bool] = set()
    for _ in range(40):
        question_id, body = new_question(numbers_harness)
        assert body["asks_year"] is date_store(numbers_harness)[question_id].asks_year
        seen.add(bool(body["asks_year"]))

    assert seen == {True, False}


def test_the_engine_speaks_the_stored_text_eagerly(numbers_harness: NumbersHarness) -> None:
    question_id, _body = new_question(numbers_harness)
    text = date_store(numbers_harness)[question_id].text

    assert [call.text for call in numbers_harness.engine.calls] == [text]
    assert re.search(r"[0-9]", text) is None


@pytest.mark.parametrize(
    "engine",
    [
        FakeSpeechEngine(error=SpeechSynthesisError("boom")),
        FakeSpeechEngine(behaviour="writes_nothing"),
    ],
    ids=["raises", "writes-nothing"],
)
def test_a_failed_synthesis_is_a_502_that_names_nothing(
    engine: FakeSpeechEngine, tmp_path: Path
) -> None:
    harness = build_numbers_harness(tmp_path, engine=engine)

    response = harness.client.post(QUESTIONS)

    assert response.status_code == 502
    assert response.json()["detail"] == FAILED_SYNTHESIS
    assert engine.calls, "the engine was never asked, so nothing was tested"
    assert HANGUL.search(response.text) is None
    assert not date_store(harness)


def test_the_audio_is_a_wav_synthesised_once(numbers_harness: NumbersHarness) -> None:
    _question_id, body = new_question(numbers_harness)

    first = numbers_harness.client.get(str(body["audio_url"]))
    second = numbers_harness.client.get(str(body["audio_url"]))

    assert first.status_code == second.status_code == 200
    assert first.content.startswith(b"RIFF")
    assert numbers_harness.engine.call_count == 1


def test_audio_for_an_unknown_question_is_404(numbers_harness: NumbersHarness) -> None:
    assert numbers_harness.client.get(f"{QUESTIONS}/nope/audio").status_code == 404


# ---------------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("asks_year", [True, False], ids=["dated", "yearless"])
def test_the_expected_date_is_correct_and_another_day_is_not(
    asks_year: bool, numbers_harness: NumbersHarness
) -> None:
    question_id, question = question_of_kind(numbers_harness, asks_year=asks_year)
    expected = question.expected
    other_day = 2 if expected.day == 1 else 1
    wrong = DateSelection(expected.year, expected.month, other_day)

    right_answer = post_answer(numbers_harness, question_id, body_of(expected))
    wrong_answer = post_answer(numbers_harness, question_id, body_of(wrong))

    assert right_answer["verdict"] == "correct"
    assert wrong_answer == {
        "verdict": "incorrect",
        "expected": body_of(expected),
        "text": question.text,
    }


def test_answering_twice_gives_the_same_verdict(numbers_harness: NumbersHarness) -> None:
    question_id, question = question_of_kind(numbers_harness, asks_year=True)
    body = body_of(question.expected)

    assert post_answer(numbers_harness, question_id, body) == post_answer(
        numbers_harness, question_id, body
    )


def test_answering_an_unknown_question_is_404(numbers_harness: NumbersHarness) -> None:
    response = numbers_harness.client.post(
        f"{QUESTIONS}/nope/answer", json={"year": None, "month": 1, "day": 1}
    )

    assert response.status_code == 404


_MISSING: Final = object()

# (asks_year, field, value): each turns the right answer into a refused one.
REFUSED: list[tuple[bool, str, object]] = [
    (True, "year", _MISSING),
    (True, "year", None),
    (False, "year", 2026),
    (True, "month", 0),
    (False, "month", 13),
    (True, "day", 0),
    (False, "day", 32),
    (True, "month", 9.5),
    (True, "month", "9"),
    (False, "month", _MISSING),
    (True, "day", _MISSING),
]


def _replaced(body: dict[str, object], field: str, value: object) -> dict[str, object]:
    changed = dict(body)
    if value is _MISSING:
        del changed[field]
    else:
        changed[field] = value
    return changed


def _assert_refused_then_answerable(
    harness: NumbersHarness, question_id: str, question: DateQuestion, body: object
) -> None:
    refused = harness.client.post(f"{QUESTIONS}/{question_id}/answer", json=body)

    assert refused.status_code == 422, refused.text
    assert question.text not in refused.text
    assert HANGUL.search(refused.text) is None
    again = post_answer(harness, question_id, body_of(question.expected))
    assert again["verdict"] == "correct"


@pytest.mark.parametrize(
    ("asks_year", "field", "value"),
    REFUSED,
    ids=[f"{'dated' if a else 'yearless'}-{f}-{v!r}" for a, f, v in REFUSED],
)
def test_a_malformed_selection_is_422_and_the_question_stays_answerable(
    asks_year: bool, field: str, value: object, numbers_harness: NumbersHarness
) -> None:
    question_id, question = question_of_kind(numbers_harness, asks_year=asks_year)
    body = _replaced(body_of(question.expected), field, value)

    _assert_refused_then_answerable(numbers_harness, question_id, question, body)


@pytest.mark.parametrize(
    ("asks_year", "body"),
    [
        (False, {"year": None, "month": 2, "day": 30}),
        (False, {"year": None, "month": 4, "day": 31}),
        (True, {"year": 2026, "month": 4, "day": 31}),
        (True, {"year": 2027, "month": 2, "day": 29}),
    ],
    ids=["yearless-30-feb", "yearless-31-april", "dated-31-april", "29-feb-2027"],
)
def test_a_day_that_is_not_real_is_422(
    asks_year: bool, body: dict[str, object], numbers_harness: NumbersHarness
) -> None:
    question_id, question = question_of_kind(numbers_harness, asks_year=asks_year)

    _assert_refused_then_answerable(numbers_harness, question_id, question, body)


@pytest.mark.parametrize(
    ("asks_year", "detail"),
    [
        (True, "This question asks for the year."),
        (False, "This question does not ask for the year."),
    ],
    ids=["dated", "yearless"],
)
def test_a_year_mismatch_says_which(
    asks_year: bool, detail: str, numbers_harness: NumbersHarness
) -> None:
    question_id, question = question_of_kind(numbers_harness, asks_year=asks_year)
    expected = question.expected
    flipped = None if asks_year else 2026

    response = numbers_harness.client.post(
        f"{QUESTIONS}/{question_id}/answer",
        json={"year": flipped, "month": expected.month, "day": expected.day},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == detail


def test_two_apps_keep_their_own_date_questions(tmp_path: Path) -> None:
    first = build_numbers_harness(tmp_path / "first")
    second = build_numbers_harness(tmp_path / "second")
    question_id, _body = new_question(first)

    response = second.client.post(
        f"{QUESTIONS}/{question_id}/answer", json={"year": None, "month": 1, "day": 1}
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------------
# The real engine, skipped by default
# ---------------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ORAL_KOREAN_TTS_E2E"),
    reason="needs the tts extra and the MeloTTS weights: ORAL_KOREAN_TTS_E2E=1, in the container",
)
def test_real_melotts_speaks_date_phrases(tmp_path: Path) -> None:
    """MeloTTS takes the irregular month names and writes a readable WAV. Acceptance, not
    pronunciation: listening is the ticket's manual check."""
    config = AppConfig()
    cache = AudioCache(
        MeloSpeechEngine(), cache_dir=tmp_path, voice=config.tts_voice, speed=config.tts_speed
    )

    for phrase in ("이천이십육 년 유월 육 일", "시월 삼십일 일"):
        with wave.open(str(cache.get_or_synthesise(phrase)), "rb") as handle:
            assert handle.getnframes() > 0
