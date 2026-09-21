"""Tests for the HTTP layer of the number exercise: T04's routes over T02 and T03.

Write-mode note: `src/oral_korean/api/routes/numbers.py` and the `speech_engine` keyword
on `create_app` now exist, matching what the framing pass of this file predicted - every
framing assertion held against the real implementation with no relaxation. Write mode
added two things the framing pass could not have known to check without reading the
implementation: the unknown-system `422` is pydantic's own validation error (a *list*
under `detail`), distinct from the plain string `detail` an `InvalidRangeError` `422`
carries - both are now pinned explicitly rather than only implied by a status code - and
coverage for the creation route's own choice to synthesise eagerly, so a `SpeechSynthesisError`
at creation time must leave nothing in the pending-question store (a `502`, the route's own
status-code choice, not one the ticket dictated). These tests are written from T04's
acceptance criteria and test contract, and they pin the contract the implementation must
satisfy - including the parts the ticket left as implementation choices:

- Routes, all under the `/api` prefix already established by `create_app`:
    - `GET /api/exercises/numbers/systems` - the numeral-systems catalogue.
    - `POST /api/exercises/numbers/questions` - draw a question and store it as pending.
    - `GET /api/exercises/numbers/questions/{question_id}/audio` - the WAV for a question.
    - `POST /api/exercises/numbers/questions/{question_id}/answer` - judge a typed answer.
- `create_app(config: AppConfig | None = None, *, speech_engine: SpeechEngine | None =
  None) -> FastAPI` gains an injectable engine, so no route test ever loads MeloTTS.
- The pending-question store lives at `app.state.number_questions: dict[str,
  NumberQuestion]` - a plain dict on the app instance, not a module global. Tests reach
  into it (via `tests/conftest.py`'s `NumbersHarness.app`) to read back the drawn number
  and Korean text that the create-question response must never leak; that a test needs
  this attribute name at all is itself part of what this file pins.
- `POST .../questions` request body: `{"system": "sino" | "native", "minimum": int,
  "maximum": int}`, all keys optional. Missing `system` defaults to Sino-Korean
  (`DEFAULT_NUMERAL_SYSTEM`). An unrecognised `system` value is a `422`, never a silent
  fallback - achieved for free by declaring the field as `NumeralSystem` on the request
  model, so pydantic itself rejects it before any route code runs. A range invalid for the
  requested system is also a `422`, surfacing T03's `InvalidRangeError` message verbatim
  (it already names the system and its supported range) rather than a re-derived one.
- `POST .../questions` response body: `{"question_id": str, "audio_url": str, "system":
  str}`. `question_id` is opaque (this file never asserts a format for it, only that it is
  non-empty and appears inside `audio_url`); the number and the Korean text are never
  fields of this response, on either system.
- `GET .../systems` response body: `{"systems": [{"system": str, "minimum": int,
  "maximum": int}, ...]}`, one entry per `NumeralSystem` member, with `minimum`/`maximum`
  read from `oral_korean.korean.numerals.supported_range` rather than hardcoded here.
- `GET .../audio` response: `200` with a `content-type` starting `audio/` and a non-empty
  body on a known id; `404` with a JSON body on an unknown one.
- `POST .../answer` request body: `{"answer": str}`, accepting any string including the
  empty one (no length constraint - a length-constrained field would turn the empty-answer
  case into a framework-level `422` that never reaches T03's `judge_answer`, which is the
  one place that gets to decide that blank input means "not a number").
- `POST .../answer` response body, always `200` on a known id: `{"verdict": "correct" |
  "incorrect" | "not_a_number", "expected_number": int, "text": str}` - the exact field
  names and string values of `oral_korean.exercises.numbers.Judgement`/`Verdict`, so the
  route layer only ever serialises T03's result instead of re-deriving it.
- **Design decision this file pins** (the ticket left it open): a non-numeric answer is
  reported as `200` with `verdict: "not_a_number"`, not a `422`. `judge_answer` already
  classifies "not a number" as one of three equally-valid outcomes of a well-formed
  request (an answer was submitted; it just was not usable), so treating it as a request
  *validation* failure would be the route re-deciding something T03 already decided.
  A `422` is reserved for a malformed request the route itself rejects before ever
  calling into T03: an unknown numeral system, or a range invalid for one.
- Answering or fetching audio for an unknown `question_id` is `404` with a JSON body,
  matching the existing `/api/...` 404 shape from `oral_korean.api.app`.

Open question resolved to make these tests concrete: the ticket does not name the route
paths beyond the epic's own "still defaults" note for the audio URL
(`/api/exercises/numbers/questions/{question_id}/audio`); the sibling paths above extend
that same `/api/exercises/numbers/...` mount point, kept in one place (`QUESTIONS_PATH`,
`SYSTEMS_PATH`, `audio_path`, `answer_path`) below so a rename costs one edit.

Every test uses the `numbers_harness` fixture from `tests/conftest.py` (or its underlying
`build_numbers_harness` when a test needs two independent app instances, or a specific
`FakeSpeechEngine` behaviour), which wires a `FakeSpeechEngine` into `create_app` - no
MeloTTS, no network, ever.

Excluded on purpose: a `SpeechSynthesisError` from the *audio-fetch* route (as opposed to
create-question) is defensive code with no reachable path through the public HTTP API in
this suite - by the time a question is stored, its audio has already been synthesised
once by the eager create-question call, so a later fetch is always a cache hit unless the
cache file is deleted or corrupted out from under the app between the two calls, which
would mean either reaching into `AudioCache`'s private digest naming (duplicating
production logic this file must not copy) or adding a bespoke stateful fake engine for a
single defensive branch. Left uncovered rather than tested via either shortcut.

Post-audit fix: a `SpeechSynthesisError`'s message is built around the text it failed to
speak (`tts/cache.py`), so the route must never relay it verbatim as a `502` detail - that
would leak the answer on a failure path instead of the success path the other tests guard.
`test_synthesis_failure_during_creation_returns_502_and_stores_nothing` pins a fixed,
text-free detail for the create-question route's own case of this.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeSpeechEngine, NumbersHarness, build_numbers_harness

from oral_korean.exercises.numbers import NumberQuestion
from oral_korean.korean.numerals import NumeralSystem, render_number, supported_range
from oral_korean.tts.base import SpeechSynthesisError

SYSTEMS_PATH = "/api/exercises/numbers/systems"
QUESTIONS_PATH = "/api/exercises/numbers/questions"


def audio_path(question_id: str) -> str:
    """The audio URL for `question_id`, built the same way the route is expected to."""
    return f"/api/exercises/numbers/questions/{question_id}/audio"


def answer_path(question_id: str) -> str:
    """The answer-submission URL for `question_id`."""
    return f"/api/exercises/numbers/questions/{question_id}/answer"


def stored_question(harness: NumbersHarness, question_id: str) -> NumberQuestion:
    """Read back the pending question the server holds for `question_id`.

    Goes straight to `app.state.number_questions` rather than any HTTP route, because no
    route is allowed to hand the number or the Korean text back before an answer is
    submitted - that is exactly the property several tests below have to check.
    """
    store: dict[str, NumberQuestion] = harness.app.state.number_questions
    return store[question_id]


def leaks(body: dict[str, object], question_id: str, needle: str) -> bool:
    """Whether `needle` appears anywhere in `body` once the opaque id is redacted.

    The id is expected to appear in the response (as `question_id` and inside
    `audio_url`), and an opaque id built from arbitrary hex digits will, essentially
    always, coincidentally contain any single digit somewhere in its length - that
    coincidence says nothing about the answer leaking. Redacting the id first is what
    keeps this check about real disclosure instead of about the shape of a UUID.
    """
    redacted = json.dumps(body).replace(question_id, "")
    return needle in redacted


# ---------------------------------------------------------------------------------
# Creating questions
# ---------------------------------------------------------------------------------


def test_default_system_creates_a_sino_question(numbers_harness: NumbersHarness) -> None:
    """No `system` in the request body still works, and draws Sino-Korean by default."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["question_id"], str) and body["question_id"]
    assert body["question_id"] in body["audio_url"]
    question = stored_question(numbers_harness, body["question_id"])
    assert question.system is NumeralSystem.SINO


def test_explicit_sino_system_stores_the_sino_rendering(numbers_harness: NumbersHarness) -> None:
    """Explicitly asking for Sino-Korean is accepted and renders in that system."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"system": "sino"})

    assert response.status_code == 200
    question = stored_question(numbers_harness, response.json()["question_id"])
    assert question.system is NumeralSystem.SINO
    assert question.text == render_number(question.number, NumeralSystem.SINO)


def test_explicit_native_system_stores_native_text_not_sino(
    numbers_harness: NumbersHarness,
) -> None:
    """Native Korean is accepted, and its text differs from what Sino would have said."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"system": "native"})

    assert response.status_code == 200
    question = stored_question(numbers_harness, response.json()["question_id"])
    assert question.system is NumeralSystem.NATIVE
    assert question.text == render_number(question.number, NumeralSystem.NATIVE)
    assert question.text != render_number(question.number, NumeralSystem.SINO)


def test_unknown_system_returns_422_and_stores_nothing(numbers_harness: NumbersHarness) -> None:
    """An unrecognised numeral system is rejected outright, never silently defaulted."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"system": "klingon"})

    assert response.status_code == 422
    assert numbers_harness.app.state.number_questions == {}


@pytest.mark.parametrize("system", ["sino", "native"])
def test_create_response_does_not_leak_the_answer(
    system: str, numbers_harness: NumbersHarness
) -> None:
    """Neither the drawn number nor its Korean text appears anywhere in the response."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"system": system})

    assert response.status_code == 200
    body = response.json()
    question = stored_question(numbers_harness, body["question_id"])

    assert not leaks(body, body["question_id"], str(question.number))
    assert not leaks(body, body["question_id"], question.text)


def test_unknown_system_422_detail_is_fastapis_validation_list_shape(
    numbers_harness: NumbersHarness,
) -> None:
    """The unknown-system 422 is pydantic's own validation error, a list under `detail` -
    distinct from the plain string `detail` an `InvalidRangeError` 422 carries. A caller
    that only ever expects the string shape must not silently misparse this one.
    """
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"system": "klingon"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail


def test_invalid_range_422_detail_is_a_plain_string(numbers_harness: NumbersHarness) -> None:
    """An `InvalidRangeError` 422, unlike the unknown-system one, carries a plain string
    `detail` - T03's message verbatim, not a pydantic error list.
    """
    response = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "native", "minimum": 1, "maximum": 100}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "engine",
    [
        FakeSpeechEngine(error=SpeechSynthesisError("boom")),
        FakeSpeechEngine(behaviour="writes_nothing"),
    ],
    ids=["engine_raises", "engine_writes_no_audio"],
)
def test_synthesis_failure_during_creation_returns_502_and_stores_nothing(
    engine: FakeSpeechEngine, tmp_path: Path
) -> None:
    """Synthesis happens eagerly at creation time, not lazily on first audio fetch: when it
    fails, the question must never be stored as pending, since its audio could never be
    served. The failure detail must not leak the Korean text that failed to synthesise -
    `AudioCache` wraps every failure with the text it was trying to speak (see
    `tts/cache.py`), so relaying that message verbatim would hand the browser the very
    answer this exercise exists to test.
    """
    harness = build_numbers_harness(tmp_path, engine=engine)
    spoken_text = render_number(5, NumeralSystem.SINO)

    response = harness.client.post(QUESTIONS_PATH, json={"minimum": 5, "maximum": 5})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert spoken_text not in detail
    assert not harness.app.state.number_questions


def test_two_questions_get_distinct_ids_and_are_both_answerable(
    numbers_harness: NumbersHarness,
) -> None:
    """Two create-question calls do not collide, and neither pending question is orphaned."""
    first = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()
    second = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()

    assert first["question_id"] != second["question_id"]

    first_question = stored_question(numbers_harness, first["question_id"])
    second_question = stored_question(numbers_harness, second["question_id"])
    first_answer = numbers_harness.client.post(
        answer_path(first["question_id"]), json={"answer": str(first_question.number)}
    )
    second_answer = numbers_harness.client.post(
        answer_path(second["question_id"]), json={"answer": str(second_question.number)}
    )

    assert first_answer.status_code == 200
    assert second_answer.status_code == 200


# ---------------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------------


def test_explicit_range_pins_the_drawn_number(numbers_harness: NumbersHarness) -> None:
    """A minimum equal to the maximum draws exactly that number, deterministically."""
    response = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "sino", "minimum": 5, "maximum": 5}
    )

    assert response.status_code == 200
    question = stored_question(numbers_harness, response.json()["question_id"])
    assert question.number == 5


def test_native_range_beyond_99_is_rejected_naming_the_system_and_its_range(
    numbers_harness: NumbersHarness,
) -> None:
    """1-100 is a fine Sino-Korean range but not a native one; the error must say so."""
    native_span = supported_range(NumeralSystem.NATIVE)

    response = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "native", "minimum": 1, "maximum": 100}
    )

    assert response.status_code == 422
    detail = json.dumps(response.json())
    assert "native" in detail
    assert str(native_span.maximum) in detail
    assert numbers_harness.app.state.number_questions == {}


def test_sino_range_up_to_100_is_accepted(numbers_harness: NumbersHarness) -> None:
    """The identical 1-100 request is fine under Sino-Korean, unlike under native."""
    response = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "sino", "minimum": 1, "maximum": 100}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(("system", "expected_status"), [("native", 422), ("sino", 200)])
def test_range_including_zero_is_rejected_only_for_native(
    system: str, expected_status: int, numbers_harness: NumbersHarness
) -> None:
    """Native Korean has no word for zero; Sino-Korean does (영), so 0 to 10 splits the two."""
    response = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": system, "minimum": 0, "maximum": 10}
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize("system", ["sino", "native"])
def test_inverted_range_is_rejected_in_both_systems(
    system: str, numbers_harness: NumbersHarness
) -> None:
    """A minimum above the maximum is an empty range, regardless of the system."""
    response = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": system, "minimum": 10, "maximum": 1}
    )

    assert response.status_code == 422
    assert numbers_harness.app.state.number_questions == {}


def test_negative_minimum_is_rejected(numbers_harness: NumbersHarness) -> None:
    """A negative minimum reaches outside every system's supported range."""
    response = numbers_harness.client.post(QUESTIONS_PATH, json={"minimum": -5})

    assert response.status_code == 422


@pytest.mark.parametrize("system", ["sino", "native"])
def test_no_range_draws_within_the_systems_own_range(
    system: str, numbers_harness: NumbersHarness
) -> None:
    """With no range given, every draw stays inside that system's own supported bounds.

    Repeated for native Korean specifically to check 100 - one past its ceiling, and the
    top of Sino-Korean's own range - never appears, which a range bug would only show up
    on some draws, not all of them.
    """
    span = supported_range(NumeralSystem(system))
    drawn: list[int] = []

    for _ in range(20):
        response = numbers_harness.client.post(QUESTIONS_PATH, json={"system": system})
        assert response.status_code == 200
        question = stored_question(numbers_harness, response.json()["question_id"])
        assert span.minimum <= question.number <= span.maximum
        drawn.append(question.number)

    if system == "native":
        assert 100 not in drawn


# ---------------------------------------------------------------------------------
# Systems catalogue
# ---------------------------------------------------------------------------------


def test_systems_catalogue_matches_the_numerals_module(numbers_harness: NumbersHarness) -> None:
    """The catalogue's ranges come from `korean.numerals`, not a second hardcoded copy."""
    response = numbers_harness.client.get(SYSTEMS_PATH)

    assert response.status_code == 200
    body = response.json()
    reported = {
        entry["system"]: (entry["minimum"], entry["maximum"]) for entry in body["systems"]
    }
    expected = {
        system.value: (supported_range(system).minimum, supported_range(system).maximum)
        for system in NumeralSystem
    }
    assert reported == expected


# ---------------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------------


def test_fetching_audio_returns_wav_bytes(numbers_harness: NumbersHarness) -> None:
    """The audio URL from a create-question response actually serves playable-looking audio."""
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()

    response = numbers_harness.client.get(created["audio_url"])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")
    assert len(response.content) > 0


def test_fetching_audio_twice_only_synthesises_once(numbers_harness: NumbersHarness) -> None:
    """A second fetch of the same question's audio is served from T02's cache, not re-synthesised.
    """
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()
    question = stored_question(numbers_harness, created["question_id"])

    first = numbers_harness.client.get(created["audio_url"])
    second = numbers_harness.client.get(created["audio_url"])

    assert first.status_code == 200
    assert second.status_code == 200
    matching_calls = [call for call in numbers_harness.engine.calls if call.text == question.text]
    assert len(matching_calls) == 1


def test_two_systems_synthesise_different_audio_for_the_same_number(
    numbers_harness: NumbersHarness,
) -> None:
    """Same drawn number, two systems: the cache key must be the text, never the number."""
    sino = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "sino", "minimum": 5, "maximum": 5}
    ).json()
    native = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "native", "minimum": 5, "maximum": 5}
    ).json()
    numbers_harness.client.get(sino["audio_url"])
    numbers_harness.client.get(native["audio_url"])

    sino_question = stored_question(numbers_harness, sino["question_id"])
    native_question = stored_question(numbers_harness, native["question_id"])
    assert sino_question.number == native_question.number == 5
    assert sino_question.text != native_question.text

    texts_synthesised = {call.text for call in numbers_harness.engine.calls}
    assert sino_question.text in texts_synthesised
    assert native_question.text in texts_synthesised


def test_audio_for_unknown_id_returns_404_with_json_body(numbers_harness: NumbersHarness) -> None:
    """An id nothing ever created 404s, instead of a stack trace or an empty audio body."""
    response = numbers_harness.client.get(audio_path("does-not-exist"))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), dict)


# ---------------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------------


def test_correct_answer_is_reported_correct(numbers_harness: NumbersHarness) -> None:
    """The drawn number, submitted as digits, is judged correct with the number and text."""
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()
    question = stored_question(numbers_harness, created["question_id"])

    response = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": str(question.number)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "correct"
    assert body["expected_number"] == question.number
    assert body["text"] == question.text


def test_wrong_answer_is_reported_incorrect(numbers_harness: NumbersHarness) -> None:
    """One more than the drawn number is judged incorrect, but still names the right answer."""
    created = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": "sino", "minimum": 5, "maximum": 5}
    ).json()
    question = stored_question(numbers_harness, created["question_id"])

    response = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": str(question.number + 1)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "incorrect"
    assert body["expected_number"] == question.number
    assert body["text"] == question.text


@pytest.mark.parametrize("system", ["sino", "native"])
def test_spoken_text_in_the_answer_matches_the_questions_system(
    system: str, numbers_harness: NumbersHarness
) -> None:
    """A wrong answer's feedback names the text that was actually spoken for that system."""
    created = numbers_harness.client.post(
        QUESTIONS_PATH, json={"system": system, "minimum": 5, "maximum": 5}
    ).json()

    response = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": "6"}
    )

    assert response.json()["text"] == render_number(5, NumeralSystem(system))


def test_whitespace_around_a_correct_answer_is_still_correct(
    numbers_harness: NumbersHarness,
) -> None:
    """Padding the typed answer with whitespace must not turn a right answer wrong."""
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()
    question = stored_question(numbers_harness, created["question_id"])

    response = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": f"  {question.number}  "}
    )

    assert response.json()["verdict"] == "correct"


def test_non_numeric_answer_is_distinguished_from_a_wrong_answer(
    numbers_harness: NumbersHarness,
) -> None:
    """Typing something unparseable is reported as its own outcome, not as "incorrect"."""
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()

    response = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": "abc"}
    )

    assert response.status_code == 200
    assert response.json()["verdict"] == "not_a_number"


def test_empty_answer_is_not_a_number_never_incorrect(numbers_harness: NumbersHarness) -> None:
    """Submitting nothing is the same distinct outcome as any other unparseable answer."""
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()

    response = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": ""}
    )

    assert response.status_code == 200
    assert response.json()["verdict"] == "not_a_number"


def test_answering_unknown_id_returns_404(numbers_harness: NumbersHarness) -> None:
    """Answering an id nothing ever created 404s rather than judging a phantom question."""
    response = numbers_harness.client.post(answer_path("does-not-exist"), json={"answer": "5"})

    assert response.status_code == 404
    assert isinstance(response.json(), dict)


def test_answering_the_same_question_twice_is_idempotent(numbers_harness: NumbersHarness) -> None:
    """Answering twice must not score, penalise or consume the question: same verdict both times."""
    created = numbers_harness.client.post(QUESTIONS_PATH, json={}).json()
    question = stored_question(numbers_harness, created["question_id"])

    first = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": str(question.number)}
    )
    second = numbers_harness.client.post(
        answer_path(created["question_id"]), json={"answer": str(question.number)}
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_isolation_between_two_app_instances(tmp_path: Path) -> None:
    """A question created against one app is unknown to a second app built by the factory."""
    first_app = build_numbers_harness(tmp_path / "first")
    second_app = build_numbers_harness(tmp_path / "second")
    created = first_app.client.post(QUESTIONS_PATH, json={}).json()

    audio_response = second_app.client.get(created["audio_url"])
    answer_response = second_app.client.post(
        answer_path(created["question_id"]), json={"answer": "1"}
    )

    assert audio_response.status_code == 404
    assert answer_response.status_code == 404
