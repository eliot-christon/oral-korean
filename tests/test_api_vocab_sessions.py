"""Tests for learn and review sessions over HTTP: vocab-sessions T03.

Written before the implementation. This file pins starting a session, what `next` hands
out, what a question may carry, audio, and lifetime; `test_api_vocab_answers.py` pins
answering and scoring. The routes, all under `/api/vocab`:

- `POST /sessions`, body `{"kind": "learn" | "review", "tag"?: str | null, "directions"?: [..],
  "size"?: int | null}` (directions default to all four, never empty; size: learn 1 to 20,
  default 5; review 1 to 100, default 20) -> `201 {"session_id", "kind", "word_count",
  "directions"}`; `409` with a string `detail` saying "nothing to learn" / "nothing to
  review" (naming the tag when one was given), no session created; `422` for a bad kind,
  size or direction, or an empty direction list.
- `POST /sessions/{session_id}/next` -> `200`, one of three shapes told apart by `"type"`:
  a **presentation** `{"type", "item_id", "korean", "translations", "audio_url",
  "progress"}`; a **question** `{"type", "item_id", "direction", "mode", "prompt",
  "audio_url", "options", "scored", "progress"}` (`prompt` null for a voice direction,
  `audio_url` null for a written one, `options` null for typing); or the **end**
  `{"type": "end", "summary": {"words": [{"korean", "translations", "correct"}],
  "word_count", "correct_count"}}`, after which the session is gone (`404`). `progress` is
  `{"done", "total"}`: words whose scored question is answered, out of the session's words.
  A pending question is handed out again, same id, until it is answered. `502` with the
  fixed detail of `api/audio.py` when synthesis fails, nothing stored, place kept.
- `GET /items/{item_id}/audio` -> `200 audio/wav` for a presentation or a voice question;
  `404` for an unknown or answered item, or a written question. A voice question's
  `audio_url` is exactly this path.
- `POST /items/{item_id}/answer`: see `test_api_vocab_answers.py`.
- Pending items live in `app.state.vocab_items` and sessions in `app.state.vocab_sessions`,
  two plain dicts per app: only their sizes are read.

The harness is `conftest.py`'s: a fake speech engine, a per-test database and a clock at
T0 = 2026-09-21 09:00 UTC; the session helpers are there too, shared with the answers file.
Words are added through the word routes. A session restricted to one direction makes its
questions predictable; the right option is found by comparing the option texts with the
word the test added. Typing is forced by seeding a word `well` and moving the clock to its
due date; multiple choice by a new word, with three distractors seeded `very_well` so they
are neither new nor due. The leak checks use the numbers suite's `leaks`, moved to
`conftest.py` and made to see Hangul (it used to search an ASCII-escaped dump).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest
from conftest import (
    ALL_DIRECTIONS,
    DISTRACTORS,
    DONT_KNOW,
    H2T,
    HANGUL_ANSWERED,
    HARNESS_START,
    KOREAN,
    MAX_ITEMS,
    SESSIONS,
    T2H,
    TRANSLATIONS,
    V2H,
    V2T,
    VOICE_DIRECTIONS,
    FakeClock,
    FakeSpeechEngine,
    Json,
    NumbersHarness,
    add_distractors,
    add_target,
    add_word,
    answered,
    ask,
    ask_by_choice,
    ask_by_typing,
    audio_path,
    build_numbers_harness,
    correct_option,
    instant,
    leaks,
    move_to_well_due_date,
    next_item,
    next_path,
    option_index,
    pending_items,
    right_choice,
    right_typed,
    sessions_held,
    start_session,
    started,
    walk,
    word_detail,
)
from fastapi.testclient import TestClient

from oral_korean.api.app import create_app
from oral_korean.tts.base import SpeechSynthesisError

T0: Final = HARNESS_START

SESSION_KEYS: Final = {"session_id", "kind", "word_count", "directions"}
PRESENTATION_KEYS: Final = {"type", "item_id", "korean", "translations", "audio_url", "progress"}
QUESTION_KEYS: Final = {
    "type",
    "item_id",
    "direction",
    "mode",
    "prompt",
    "audio_url",
    "options",
    "scored",
    "progress",
}
SYNTHESIS_FAILURE_DETAIL: Final = "Could not synthesise audio for this question."

NEW_WORDS: Final = (
    ("사과", "apple"),
    ("배", "pear"),
    ("감", "persimmon"),
    ("포도", "grape"),
    ("수박", "watermelon"),
    ("딸기", "strawberry"),
    ("귤", "tangerine"),
)


@pytest.fixture(name="harness")
def make_harness(tmp_path: Path) -> NumbersHarness:
    return build_numbers_harness(tmp_path)


def presented(items: list[Json]) -> list[str]:
    return [item["korean"] for item in items if item["type"] == "presentation"]


def without_options(question: Json) -> Json:
    return {key: value for key, value in question.items() if key != "options"}


# ---------------------------------------------------------------------------------
# Starting a session
# ---------------------------------------------------------------------------------


def test_learn_with_the_default_size_takes_the_five_oldest_new_words(
    harness: NumbersHarness,
) -> None:
    for korean, translation in NEW_WORDS:
        add_word(harness.client, korean, translation)
        harness.clock.advance(timedelta(minutes=1))

    response = start_session(harness.client, "learn")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == SESSION_KEYS
    assert isinstance(body["session_id"], str) and body["session_id"]
    assert body["kind"] == "learn"
    assert body["word_count"] == 5
    assert sorted(body["directions"]) == sorted(ALL_DIRECTIONS)
    items = walk(harness.client, body["session_id"], DONT_KNOW)
    assert presented(items) == [korean for korean, _ in NEW_WORDS[:5]]


def test_learn_with_a_tag_takes_only_its_new_words_and_never_a_seeded_one(
    harness: NumbersHarness,
) -> None:
    client = harness.client
    add_word(client, "사과", "apple", tags=["food"])
    add_word(client, "가다", "to go", tags=["verb"])
    add_word(client, "배", "pear", tags=["food"], familiarity="well")
    add_word(client, "감", "persimmon", tags=["food"])

    response = start_session(client, "learn", tag="food")

    assert response.status_code == 201
    assert response.json()["word_count"] == 2
    items = walk(client, response.json()["session_id"], DONT_KNOW)
    assert presented(items) == ["사과", "감"]


def test_a_word_seeded_very_well_is_due_for_review_only_from_its_next_review(
    harness: NumbersHarness,
) -> None:
    """Its due date is read from the word route, not assumed: the ticket's "nine days" is
    inside the range FSRS may fuzz an eight-day first delay to."""
    client = harness.client
    word_id = add_word(client, "배", "pear", familiarity="very_well")["id"]
    add_word(client, "감", "persimmon")
    assert start_session(client, "review").status_code == 409

    due = instant(word_detail(client, word_id)["statistics"]["next_review"])
    harness.clock.advance(due - T0)
    response = start_session(client, "review", directions=[H2T])

    assert response.status_code == 201
    assert response.json()["word_count"] == 1
    question = next_item(client, response.json()["session_id"])
    assert question["type"] == "question"
    assert question["prompt"] == "배"


def test_review_serves_the_most_overdue_word_first(harness: NumbersHarness) -> None:
    client = harness.client
    add_word(client, "사과", "apple", familiarity="well")
    harness.clock.advance(timedelta(hours=1))
    add_word(client, "배", "pear", familiarity="well")
    move_to_well_due_date(harness)

    session_id = started(client, "review", directions=[H2T], size=1)

    assert next_item(client, session_id)["prompt"] == "사과"


def test_learn_with_nothing_new_is_a_409_saying_so_and_starts_nothing(
    harness: NumbersHarness,
) -> None:
    add_word(harness.client, "배", "pear", familiarity="well")

    response = start_session(harness.client, "learn")

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    assert "nothing to learn" in response.json()["detail"].lower()
    assert sessions_held(harness) == 0


def test_learn_with_a_tag_holding_nothing_new_names_the_tag(harness: NumbersHarness) -> None:
    add_word(harness.client, "가다", "to go", tags=["verb"])

    response = start_session(harness.client, "learn", tag="food")

    assert response.status_code == 409
    assert "nothing to learn" in response.json()["detail"].lower()
    assert "food" in response.json()["detail"]
    assert sessions_held(harness) == 0


def test_review_with_nothing_due_is_a_409_saying_so_and_starts_nothing(
    harness: NumbersHarness,
) -> None:
    add_word(harness.client, "사과", "apple")
    add_word(harness.client, "배", "pear", familiarity="well")

    response = start_session(harness.client, "review")

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    assert "nothing to review" in response.json()["detail"].lower()
    assert sessions_held(harness) == 0


def add_one_new_and_one_due(harness: NumbersHarness) -> None:
    """So that a refused start is refused for its request, never for want of words."""
    add_word(harness.client, "사과", "apple")
    add_word(harness.client, "배", "pear", familiarity="well")
    move_to_well_due_date(harness)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"kind": "learn", "size": 0}, id="learn-size-0"),
        pytest.param({"kind": "review", "size": 0}, id="review-size-0"),
        pytest.param({"kind": "learn", "size": -1}, id="negative-size"),
        pytest.param({"kind": "learn", "size": 21}, id="learn-size-21"),
        pytest.param({"kind": "review", "size": 101}, id="review-size-101"),
        pytest.param({"kind": "learn", "size": "five"}, id="non-numeric-size"),
        pytest.param({"kind": "cram"}, id="unknown-kind"),
        pytest.param({}, id="no-kind"),
        pytest.param({"kind": "learn", "directions": ["smell"]}, id="unknown-direction"),
        pytest.param({"kind": "learn", "directions": [H2T, "smell"]}, id="one-bad-direction"),
        pytest.param({"kind": "learn", "directions": []}, id="no-direction"),
    ],
)
def test_a_bad_start_request_is_a_422_and_starts_nothing(
    harness: NumbersHarness, body: dict[str, object]
) -> None:
    add_one_new_and_one_due(harness)

    response = harness.client.post(SESSIONS, json=body)

    assert response.status_code == 422
    assert sessions_held(harness) == 0


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"kind": "learn", "size": 1}, id="learn-size-1"),
        pytest.param({"kind": "learn", "size": 20}, id="learn-size-20"),
        pytest.param({"kind": "review", "size": 1}, id="review-size-1"),
        pytest.param({"kind": "review", "size": 100}, id="review-size-100"),
        pytest.param({"kind": "learn", "size": None, "tag": None}, id="explicit-nulls"),
    ],
)
def test_sizes_at_either_end_of_their_range_are_accepted(
    harness: NumbersHarness, body: dict[str, object]
) -> None:
    add_one_new_and_one_due(harness)

    response = harness.client.post(SESSIONS, json=body)

    assert response.status_code == 201, response.text
    assert response.json()["word_count"] == 1


def test_the_start_response_echoes_the_directions_asked_for(harness: NumbersHarness) -> None:
    add_target(harness.client)

    response = start_session(harness.client, "learn", directions=[V2H])

    assert response.status_code == 201
    assert response.json()["kind"] == "learn"
    assert response.json()["directions"] == [V2H]


def test_an_unknown_session_is_a_404(harness: NumbersHarness) -> None:
    response = harness.client.post(next_path("no-such-session"))

    assert response.status_code == 404
    assert "detail" in response.json()


# ---------------------------------------------------------------------------------
# Presentations, questions and the end
# ---------------------------------------------------------------------------------


def test_a_learn_session_presents_the_word_then_asks_it_by_choice(
    harness: NumbersHarness,
) -> None:
    client = harness.client
    add_target(client)
    add_distractors(client)
    session_id = started(client, "learn", directions=[H2T])

    presentation = next_item(client, session_id)
    audio = client.get(presentation["audio_url"])
    question = next_item(client, session_id)

    assert set(presentation) == PRESENTATION_KEYS
    assert presentation["type"] == "presentation"
    assert presentation["korean"] == KOREAN
    assert presentation["translations"] == TRANSLATIONS
    assert presentation["progress"] == {"done": 0, "total": 1}
    assert presentation["audio_url"] == audio_path(presentation["item_id"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content.startswith(b"RIFF")
    # Once the session moves on, the presentation is gone with its audio.
    assert client.get(presentation["audio_url"]).status_code == 404
    assert question["type"] == "question"
    assert question["item_id"] != presentation["item_id"]
    assert question["scored"] is True
    assert question["mode"] == "choice"
    assert question["prompt"] == KOREAN
    assert 2 <= len(question["options"]) <= 4


def test_two_next_calls_at_once_hand_out_one_question(harness: NumbersHarness) -> None:
    """A React effect run twice sends two `next` calls together: one item, handed out twice."""
    client = harness.client
    add_target(client, familiarity="well")
    move_to_well_due_date(harness)
    session_id = started(client, "review", directions=[T2H])
    barrier = threading.Barrier(2, timeout=5.0)

    def call_next() -> Json:
        barrier.wait()
        return next_item(client, session_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [future.result() for future in [pool.submit(call_next) for _ in range(2)]]

    assert first == second
    assert first["type"] == "question"
    assert pending_items(harness) == 1


def test_next_twice_without_answering_returns_the_same_question(
    harness: NumbersHarness,
) -> None:
    """A hard word cannot be skipped to dodge an `again`."""
    asked = ask_by_typing(harness, T2H)

    again = next_item(harness.client, asked.session_id)

    assert again == asked.question
    assert pending_items(harness) == 1


def test_after_the_last_answer_next_is_the_end_and_the_session_is_dropped(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_typing(harness, T2H)
    answered(harness.client, asked.item_id, {"answer": KOREAN})

    end = next_item(harness.client, asked.session_id)

    assert end == {
        "type": "end",
        "summary": {
            "words": [{"korean": KOREAN, "translations": TRANSLATIONS, "correct": True}],
            "word_count": 1,
            "correct_count": 1,
        },
    }
    assert harness.client.post(next_path(asked.session_id)).status_code == 404
    assert sessions_held(harness) == 0


def test_the_summary_reports_first_attempts_and_practice_comes_last(
    harness: NumbersHarness,
) -> None:
    """Most overdue first (a tie broken by id), a missed word's practice at the end."""
    client = harness.client
    add_target(client, familiarity="well")
    add_word(client, "배", "pear", familiarity="well")
    move_to_well_due_date(harness)
    session_id = started(client, "review", directions=[T2H])

    first = next_item(client, session_id)
    answered(client, first["item_id"], {"answer": "감"})
    second = next_item(client, session_id)
    answered(client, second["item_id"], {"answer": "배"})
    practice = next_item(client, session_id)
    # After the lapse the word is weak again, so its practice is asked by choice.
    practice_answer = (
        right_choice(practice) if practice["options"] is not None else right_typed(T2H)
    )
    answered(client, practice["item_id"], practice_answer)
    end = next_item(client, session_id)

    assert ("apple" in first["prompt"], first["scored"]) == (True, True)
    assert ("pear" in second["prompt"], second["scored"]) == (True, True)
    assert ("apple" in practice["prompt"], practice["scored"]) == (True, False)
    assert end["summary"] == {
        "words": [
            {"korean": KOREAN, "translations": TRANSLATIONS, "correct": False},
            {"korean": "배", "translations": ["pear"], "correct": True},
        ],
        "word_count": 2,
        "correct_count": 1,
    }


def test_progress_counts_the_words_whose_scored_question_is_answered(
    harness: NumbersHarness,
) -> None:
    """사과 missed, 수박 right, then 사과's practice: progress moves on scored answers only."""
    client = harness.client
    add_target(client)
    add_word(client, "수박", "watermelon")
    add_distractors(client)
    session_id = started(client, "learn", directions=[H2T])
    seen = []

    for _ in range(MAX_ITEMS):
        item = next_item(client, session_id)
        if item["type"] == "end":
            break
        seen.append((item["type"], item["progress"]))
        if item["type"] == "question":
            right = option_index(item, "watermelon" if item["prompt"] == "수박" else "apple")
            wrong = next(i for i in range(len(item["options"])) if i != right)
            missed = item["prompt"] == KOREAN and item["scored"]
            answered(client, item["item_id"], {"choice": wrong if missed else right})

    assert seen == [
        ("presentation", {"done": 0, "total": 2}),
        ("question", {"done": 0, "total": 2}),
        ("presentation", {"done": 1, "total": 2}),
        ("question", {"done": 1, "total": 2}),
        ("question", {"done": 2, "total": 2}),
    ]


# ---------------------------------------------------------------------------------
# What a question may carry
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["choice", "typing"])
@pytest.mark.parametrize("direction", ALL_DIRECTIONS)
def test_a_question_carries_exactly_the_documented_fields(
    harness: NumbersHarness, direction: str, mode: str
) -> None:
    question = ask(harness, direction, mode).question

    assert set(question) == QUESTION_KEYS
    assert question["type"] == "question"
    assert question["direction"] == direction
    assert question["mode"] == mode
    assert question["scored"] is True
    assert question["progress"] == {"done": 0, "total": 1}
    if direction in VOICE_DIRECTIONS:
        assert question["prompt"] is None
        assert question["audio_url"] == audio_path(question["item_id"])
    else:
        assert question["audio_url"] is None
    if direction == H2T:
        assert question["prompt"] == KOREAN
    if direction == T2H:
        assert all(translation in question["prompt"] for translation in TRANSLATIONS)
    if mode == "typing":
        assert question["options"] is None
    else:
        assert 2 <= len(question["options"]) <= 4
        assert all(isinstance(option, str) for option in question["options"])


def test_a_hangul_to_translation_typing_question_names_no_translation(
    harness: NumbersHarness,
) -> None:
    question = ask_by_typing(harness, H2T).question

    for translation in TRANSLATIONS:
        assert not leaks(question, question["item_id"], translation)


def test_a_translation_to_hangul_typing_question_names_no_korean(
    harness: NumbersHarness,
) -> None:
    question = ask_by_typing(harness, T2H).question

    assert not leaks(question, question["item_id"], KOREAN)


@pytest.mark.parametrize("direction", VOICE_DIRECTIONS)
def test_a_voice_typing_question_names_neither_side_of_the_word(
    harness: NumbersHarness, direction: str
) -> None:
    """The audio URL is the item's own route and nothing else: no word id, no text."""
    question = ask_by_typing(harness, direction).question

    for needle in [KOREAN, *TRANSLATIONS]:
        assert not leaks(question, question["item_id"], needle)
    assert question["audio_url"] == audio_path(question["item_id"])


def test_a_voice_to_translation_choice_question_names_no_korean(
    harness: NumbersHarness,
) -> None:
    question = ask_by_choice(harness, V2T).question

    assert not leaks(question, question["item_id"], KOREAN)


def test_a_voice_to_hangul_choice_question_names_the_korean_only_among_its_options(
    harness: NumbersHarness,
) -> None:
    question = ask_by_choice(harness, V2H).question

    assert question["options"].count(KOREAN) == 1
    assert not leaks(without_options(question), question["item_id"], KOREAN)
    for translation in TRANSLATIONS:
        assert not leaks(question, question["item_id"], translation)


@pytest.mark.parametrize("direction", ALL_DIRECTIONS)
def test_the_right_option_appears_once_and_only_among_the_options(
    harness: NumbersHarness, direction: str
) -> None:
    """Nothing else names it; the pinned key set leaves no field to point at it."""
    question = ask_by_choice(harness, direction).question
    answer_side = [KOREAN] if direction in HANGUL_ANSWERED else TRANSLATIONS

    assert question["options"].count(correct_option(question)) == 1
    for needle in answer_side:
        assert not leaks(without_options(question), question["item_id"], needle)


@pytest.mark.parametrize("direction", [H2T, T2H])
def test_a_written_question_has_no_audio(harness: NumbersHarness, direction: str) -> None:
    asked = ask_by_typing(harness, direction)

    assert harness.client.get(audio_path(asked.item_id)).status_code == 404


def test_the_distractors_are_the_users_own_words(harness: NumbersHarness) -> None:
    """Candidates are the whole vocabulary: every wrong option is a word the test added."""
    question = ask_by_choice(harness, V2H).question
    own_words = {KOREAN, *(korean for korean, _ in DISTRACTORS)}

    assert set(question["options"]) <= own_words


# ---------------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------------


def test_a_voice_question_serves_its_audio_until_it_is_answered(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_typing(harness, V2H)

    audio = harness.client.get(asked.question["audio_url"])
    answered(harness.client, asked.item_id, {"answer": KOREAN})

    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert harness.client.get(asked.question["audio_url"]).status_code == 404


def test_one_word_heard_in_two_sessions_is_synthesised_once(harness: NumbersHarness) -> None:
    client = harness.client
    add_target(client, familiarity="well")
    move_to_well_due_date(harness)
    first = next_item(client, started(client, "review", directions=[V2H]))
    second = next_item(client, started(client, "review", directions=[V2T]))

    for question in (first, second):
        assert client.get(question["audio_url"]).status_code == 200
    assert [call.text for call in harness.engine.calls].count(KOREAN) == 1


def test_a_synthesis_failure_is_a_text_free_502_and_the_session_keeps_its_place(
    tmp_path: Path,
) -> None:
    """The engine's own message names the word, as the cache's does: the 502 must not."""
    engine = FakeSpeechEngine(error=SpeechSynthesisError(f"could not speak {KOREAN}"))
    harness = build_numbers_harness(tmp_path, engine=engine)
    client = harness.client
    add_target(client, familiarity="well")
    harness.clock.advance(timedelta(hours=1))
    add_word(client, "배", "pear", familiarity="well")
    move_to_well_due_date(harness)
    session_id = started(client, "review", directions=[V2T])

    failed = client.post(next_path(session_id))

    assert failed.status_code == 502
    assert failed.json()["detail"] == SYNTHESIS_FAILURE_DETAIL
    for needle in [KOREAN, *TRANSLATIONS, "배", "pear"]:
        assert needle not in failed.text
    assert pending_items(harness) == 0
    engine.error = None
    question = next_item(client, session_id)
    assert question["progress"] == {"done": 0, "total": 2}
    assert engine.calls[-1].text == engine.calls[0].text == KOREAN
    assert answered(client, question["item_id"], {"answer": "apple"})["korean"] == KOREAN


def test_a_synthesis_failure_on_a_presentation_keeps_it_too(tmp_path: Path) -> None:
    engine = FakeSpeechEngine(error=SpeechSynthesisError("boom"))
    harness = build_numbers_harness(tmp_path, engine=engine)
    add_target(harness.client)
    add_distractors(harness.client)
    session_id = started(harness.client, "learn", directions=[H2T])

    failed = harness.client.post(next_path(session_id))
    pending_after_failure = pending_items(harness)
    engine.error = None
    retried = next_item(harness.client, session_id)

    assert failed.status_code == 502
    assert failed.json()["detail"] == SYNTHESIS_FAILURE_DETAIL
    assert pending_after_failure == 0
    assert (retried["type"], retried["korean"]) == ("presentation", KOREAN)


# ---------------------------------------------------------------------------------
# Lifetime and isolation
# ---------------------------------------------------------------------------------


def test_a_session_started_on_one_app_is_unknown_to_another(tmp_path: Path) -> None:
    first = build_numbers_harness(tmp_path / "first")
    second = build_numbers_harness(tmp_path / "second")
    add_target(first.client)
    session_id = started(first.client, "learn", directions=[H2T])

    assert second.client.post(next_path(session_id)).status_code == 404
    assert next_item(first.client, session_id)["type"] == "presentation"
    assert sessions_held(second) == 0


def test_a_new_app_on_the_same_database_forgets_the_session_but_keeps_its_scores(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_typing(harness, T2H)
    answered(harness.client, asked.item_id, {"answer": KOREAN})
    restarted = TestClient(
        create_app(
            harness.config, speech_engine=FakeSpeechEngine(), clock=FakeClock(harness.clock.now)
        )
    )

    assert restarted.post(next_path(asked.session_id)).status_code == 404
    history = word_detail(restarted, asked.word_id)["history"]
    assert [(row["is_seed"], row["direction"]) for row in history] == [(True, None), (False, T2H)]
