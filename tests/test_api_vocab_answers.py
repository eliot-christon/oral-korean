"""Tests for answering a vocab question over HTTP, and how it scores: vocab-sessions T03.

Written before the implementation; the session routes and the helpers are documented in
`test_api_vocab_sessions.py` and `conftest.py`. The route pinned here:

- `POST /api/vocab/items/{item_id}/answer`, a body with exactly one of `{"answer": str}`,
  `{"choice": int}` or `{"dont_know": true}` -> `200 {"correct", "korean", "translations",
  "correct_option", "scored", "statistics_before", "statistics_after"}`. The statistics are
  the word routes' own JSON shape, read at the clock's instant; both null when the word was
  deleted while its question was pending. `correct_option` is the right option's text for
  multiple choice, null for typing. `scored` is false for a practice question and for a
  deleted word.
- The answer **consumes** the question: a second answer is `404`, and of two submitted at
  once exactly one is `200`. A body that does not fit the question (text for multiple
  choice, a choice for typing, an index out of range, zero or several of the three fields)
  is `422` and does **not** consume it; a presentation's id is `422` too.
- A scored answer grades the word with T02's mapping (choice right `hard`, typing right
  `good`, anything wrong `again`), applies it with `srs/` at the clock's instant, and writes
  the new state and a history row in one transaction. The word detail's history entries
  gain `direction`, `mode` and `correct`, null for a seed.
- A question is a snapshot: a word edited while its question is pending is judged against
  the text it was asked with.

Expected FSRS figures come from `srs/` with fuzzing off, never re-derived: the routes fuzz,
so stabilities are compared everywhere and dates only for a first delay of a day, which FSRS
never fuzzes.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Final

import pytest
from conftest import (
    DONT_KNOW,
    H2T,
    HARNESS_START,
    KOREAN,
    T2H,
    TRANSLATIONS,
    V2H,
    V2T,
    WORDS,
    NumbersHarness,
    add_distractors,
    add_target,
    answer,
    answered,
    ask,
    ask_by_choice,
    ask_by_typing,
    build_numbers_harness,
    correct_option,
    instant,
    next_item,
    next_path,
    pending_items,
    right_choice,
    right_typed,
    seeded_well,
    started,
    walk,
    word_detail,
    wrong_choice,
)
from httpx import Response

from oral_korean.srs.memory import Grade, apply_grade

T0: Final = HARNESS_START

VERDICT_KEYS: Final = {
    "correct",
    "korean",
    "translations",
    "correct_option",
    "scored",
    "statistics_before",
    "statistics_after",
}
ANSWER_CONTEXT_KEYS: Final = {"direction", "mode", "correct"}


@pytest.fixture(name="harness")
def make_harness(tmp_path: Path) -> NumbersHarness:
    return build_numbers_harness(tmp_path)


# ---------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------


def test_a_new_word_answered_right_by_choice_is_scored_hard(harness: NumbersHarness) -> None:
    asked = ask_by_choice(harness, H2T)
    before = word_detail(harness.client, asked.word_id)
    expected, _ = apply_grade(None, Grade.HARD, T0, fuzzing=False)

    verdict = answered(harness.client, asked.item_id, right_choice(asked.question))

    after = word_detail(harness.client, asked.word_id)
    assert set(verdict) == VERDICT_KEYS
    assert (verdict["correct"], verdict["scored"]) == (True, True)
    assert (verdict["korean"], verdict["translations"]) == (KOREAN, TRANSLATIONS)
    assert verdict["correct_option"] == correct_option(asked.question)
    assert verdict["statistics_before"] == before["statistics"]
    assert verdict["statistics_after"] == after["statistics"]
    assert after["statistics"]["review_count"] == 1
    assert after["statistics"]["stability"] == expected.stability
    assert instant(after["statistics"]["next_review"]) == expected.next_review
    newest = after["history"][-1]
    assert (newest["grade"], newest["is_seed"]) == ("hard", False)
    assert (newest["direction"], newest["mode"], newest["correct"]) == (H2T, "choice", True)


def test_a_wrong_choice_records_again_and_its_practice_question_is_not_scored(
    harness: NumbersHarness,
) -> None:
    client = harness.client
    asked = ask_by_choice(harness, H2T)
    expected, _ = apply_grade(None, Grade.AGAIN, T0, fuzzing=False)

    verdict = answered(client, asked.item_id, wrong_choice(asked.question))
    after_miss = word_detail(client, asked.word_id)
    practice = next_item(client, asked.session_id)
    practice_answer = (
        right_choice(practice) if practice["options"] is not None else right_typed(H2T)
    )
    practice_verdict = answered(client, practice["item_id"], practice_answer)

    assert (verdict["correct"], verdict["scored"]) == (False, True)
    assert after_miss["statistics"]["stability"] == expected.stability
    assert [(row["grade"], row["correct"]) for row in after_miss["history"]] == [
        ("again", False)
    ]
    assert practice["type"] == "question"
    assert practice["item_id"] != asked.item_id
    assert (practice["prompt"], practice["scored"]) == (KOREAN, False)
    assert (practice_verdict["correct"], practice_verdict["scored"]) == (True, False)
    assert practice_verdict["statistics_before"] == after_miss["statistics"]
    assert practice_verdict["statistics_after"] == after_miss["statistics"]
    assert word_detail(client, asked.word_id) == after_miss


def test_a_word_known_well_is_typed_at_its_due_date_and_a_right_answer_records_good(
    harness: NumbersHarness,
) -> None:
    """Typing weighs more: the stability rises past what `hard` would have made it."""
    asked = ask_by_typing(harness, T2H)
    state = seeded_well()
    good, _ = apply_grade(state, Grade.GOOD, state.next_review, fuzzing=False)
    hard, _ = apply_grade(state, Grade.HARD, state.next_review, fuzzing=False)

    verdict = answered(harness.client, asked.item_id, {"answer": KOREAN})

    after = word_detail(harness.client, asked.word_id)
    assert (verdict["correct"], verdict["scored"]) == (True, True)
    assert verdict["correct_option"] is None
    assert after["statistics"]["stability"] == good.stability
    assert after["statistics"]["stability"] > hard.stability
    assert after["statistics"]["review_count"] == 1
    newest = after["history"][-1]
    assert newest["grade"] == "good"
    assert (newest["direction"], newest["mode"], newest["correct"]) == (T2H, "typing", True)


@pytest.mark.parametrize(
    ("direction", "typed"),
    [
        pytest.param(T2H, "사 과", id="hangul-spacing-ignored"),
        pytest.param(V2H, " 사과 ", id="hangul-surrounding-space-ignored"),
        pytest.param(H2T, "Apple!", id="translation-case-and-punctuation-ignored"),
        pytest.param(V2T, "  POMME ", id="any-accepted-translation"),
    ],
)
def test_typed_answers_are_judged_by_the_exercise_rules(
    harness: NumbersHarness, direction: str, typed: str
) -> None:
    asked = ask_by_typing(harness, direction)

    verdict = answered(harness.client, asked.item_id, {"answer": typed})

    assert verdict["correct"] is True


def test_a_wrong_typed_answer_records_again_as_a_lapse(harness: NumbersHarness) -> None:
    asked = ask_by_typing(harness, H2T)
    state = seeded_well()
    expected, _ = apply_grade(state, Grade.AGAIN, state.next_review, fuzzing=False)

    verdict = answered(harness.client, asked.item_id, {"answer": "pear"})

    after = word_detail(harness.client, asked.word_id)
    assert (verdict["correct"], verdict["scored"]) == (False, True)
    assert after["statistics"]["stability"] == expected.stability
    assert after["statistics"]["lapse_count"] == 1
    newest = after["history"][-1]
    assert newest["grade"] == "again"
    assert (newest["direction"], newest["mode"], newest["correct"]) == (H2T, "typing", False)


def test_a_blank_typed_answer_is_wrong_not_malformed(harness: NumbersHarness) -> None:
    asked = ask_by_typing(harness, T2H)

    verdict = answered(harness.client, asked.item_id, {"answer": "   "})

    assert (verdict["correct"], verdict["scored"]) == (False, True)
    assert word_detail(harness.client, asked.word_id)["history"][-1]["grade"] == "again"


def test_i_dont_know_on_a_choice_question_is_wrong_and_records_again(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_choice(harness, V2T)

    verdict = answered(harness.client, asked.item_id, DONT_KNOW)

    assert (verdict["correct"], verdict["scored"]) == (False, True)
    assert verdict["correct_option"] == correct_option(asked.question)
    history = word_detail(harness.client, asked.word_id)["history"]
    assert [(row["grade"], row["correct"]) for row in history] == [("again", False)]


def test_a_word_missed_every_time_is_scored_once_and_the_session_ends(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_choice(harness, H2T)
    answered(harness.client, asked.item_id, DONT_KNOW)

    items = walk(harness.client, asked.session_id, DONT_KNOW)

    questions = [item for item in items if item["type"] == "question"]
    assert [question["scored"] for question in questions] == [False, False]
    assert items[-1]["summary"]["correct_count"] == 0
    assert len(word_detail(harness.client, asked.word_id)["history"]) == 1


# ---------------------------------------------------------------------------------
# Answering once
# ---------------------------------------------------------------------------------


def test_a_second_answer_is_a_404_and_changes_nothing(harness: NumbersHarness) -> None:
    asked = ask_by_choice(harness, H2T)
    answered(harness.client, asked.item_id, right_choice(asked.question))
    after_first = word_detail(harness.client, asked.word_id)

    second = answer(harness.client, asked.item_id, right_choice(asked.question))

    assert second.status_code == 404
    assert asked.item_id in second.json()["detail"]
    assert word_detail(harness.client, asked.word_id) == after_first


def test_two_answers_submitted_at_once_score_once(harness: NumbersHarness) -> None:
    asked = ask_by_choice(harness, H2T)
    body = right_choice(asked.question)
    barrier = threading.Barrier(2, timeout=5.0)

    def submit() -> int:
        barrier.wait()
        return answer(harness.client, asked.item_id, body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        statuses = sorted(future.result() for future in futures)

    assert statuses == [200, 404]
    after = word_detail(harness.client, asked.word_id)
    assert len(after["history"]) == 1
    assert after["statistics"]["review_count"] == 1


def test_a_next_arriving_while_an_answer_is_scored_waits_for_it(
    harness: NumbersHarness,
) -> None:
    """The window between taking a question and recording it in the plan: a `next` landing
    there must not be handed the same word's scored question a second time.

    Scoring reads the injected clock after the take, so the clock starts that `next` in a
    thread and gives it time to run before the answer goes on."""
    asked = ask_by_typing(harness, T2H)
    real_clock = harness.app.state.clock
    raced: list[Response] = []
    racers: list[threading.Thread] = []

    def clock_that_races_a_next() -> datetime:
        if not racers:
            racer = threading.Thread(
                target=lambda: raced.append(harness.client.post(next_path(asked.session_id)))
            )
            racers.append(racer)
            racer.start()
            racer.join(timeout=0.5)
        now: datetime = real_clock()
        return now

    harness.app.state.clock = clock_that_races_a_next
    verdict = answered(harness.client, asked.item_id, right_typed(T2H))
    racers[0].join(timeout=5.0)

    assert verdict["scored"] is True
    assert raced[0].status_code == 200
    assert raced[0].json()["type"] == "end"
    assert len(word_detail(harness.client, asked.word_id)["history"]) == 2


@pytest.mark.parametrize(
    ("mode", "body"),
    [
        pytest.param("choice", {"choice": 99}, id="choice-out-of-range"),
        pytest.param("choice", {"choice": -1}, id="negative-choice"),
        pytest.param("choice", {"choice": "first"}, id="non-numeric-choice"),
        pytest.param("choice", {"answer": "apple"}, id="text-for-a-choice-question"),
        pytest.param("typing", {"choice": 0}, id="choice-for-a-typing-question"),
        pytest.param("choice", {}, id="empty-body"),
        pytest.param("choice", {"answer": "apple", "choice": 0}, id="answer-and-choice"),
        pytest.param("typing", {"answer": KOREAN, "dont_know": True}, id="answer-and-dont-know"),
    ],
)
def test_a_malformed_answer_is_a_422_and_leaves_the_question_answerable(
    harness: NumbersHarness, mode: str, body: Mapping[str, object]
) -> None:
    asked = ask(harness, H2T if mode == "choice" else T2H, mode)
    before = word_detail(harness.client, asked.word_id)

    response = answer(harness.client, asked.item_id, body)

    assert response.status_code == 422
    assert pending_items(harness) == 1
    assert word_detail(harness.client, asked.word_id) == before
    right = right_choice(asked.question) if mode == "choice" else right_typed(T2H)
    assert answered(harness.client, asked.item_id, right)["scored"] is True


def test_answering_a_presentation_is_a_422_and_records_nothing(
    harness: NumbersHarness,
) -> None:
    word_id = add_target(harness.client)
    add_distractors(harness.client)
    session_id = started(harness.client, "learn", directions=[H2T])
    presentation = next_item(harness.client, session_id)

    response = answer(harness.client, presentation["item_id"], DONT_KNOW)

    assert response.status_code == 422
    after = word_detail(harness.client, word_id)
    assert after["history"] == []
    assert after["statistics"]["review_count"] == 0


def test_an_unknown_item_is_a_404_on_both_item_routes(harness: NumbersHarness) -> None:
    answer_response = answer(harness.client, "no-such-item", DONT_KNOW)
    audio_response = harness.client.get("/api/vocab/items/no-such-item/audio")

    assert answer_response.status_code == 404
    assert "no-such-item" in answer_response.json()["detail"]
    assert audio_response.status_code == 404


# ---------------------------------------------------------------------------------
# A word changed while its question is pending
# ---------------------------------------------------------------------------------


def test_a_word_deleted_while_its_question_is_pending_is_judged_but_not_scored(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_choice(harness, H2T)
    assert harness.client.delete(f"{WORDS}/{asked.word_id}").status_code == 204

    verdict = answered(harness.client, asked.item_id, right_choice(asked.question))

    assert (verdict["correct"], verdict["scored"]) == (True, False)
    assert (verdict["korean"], verdict["translations"]) == (KOREAN, TRANSLATIONS)
    assert verdict["statistics_before"] is None
    assert verdict["statistics_after"] is None
    with closing(sqlite3.connect(harness.config.database_path)) as raw:
        rows = raw.execute(
            "SELECT COUNT(*) FROM reviews WHERE word_id = ?", (asked.word_id,)
        ).fetchone()[0]
    assert rows == 0
    assert next_item(harness.client, asked.session_id)["type"] == "end"


def test_a_word_edited_while_its_question_is_pending_is_judged_against_the_old_text(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_typing(harness, H2T)
    edit = {"korean": KOREAN, "translations": "pear", "tags": []}
    assert harness.client.put(f"{WORDS}/{asked.word_id}", json=edit).status_code == 200

    verdict = answered(harness.client, asked.item_id, {"answer": "apple"})

    assert verdict["correct"] is True
    assert verdict["translations"] == TRANSLATIONS


# ---------------------------------------------------------------------------------
# What the verdict and the history show
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("typed", [KOREAN, "감"], ids=["right", "wrong"])
def test_the_verdict_carries_the_word_and_its_statistics_before_and_after(
    harness: NumbersHarness, typed: str
) -> None:
    asked = ask_by_typing(harness, T2H)
    before = word_detail(harness.client, asked.word_id)["statistics"]

    verdict = answered(harness.client, asked.item_id, {"answer": typed})

    assert (verdict["korean"], verdict["translations"]) == (KOREAN, TRANSLATIONS)
    assert verdict["statistics_before"] == before
    after = verdict["statistics_after"]
    assert after == word_detail(harness.client, asked.word_id)["statistics"]
    assert (before["review_count"], after["review_count"]) == (0, 1)
    assert instant(after["next_review"]) > instant(before["next_review"])


def test_the_word_history_shows_the_answer_context_and_nulls_for_the_seed(
    harness: NumbersHarness,
) -> None:
    asked = ask_by_typing(harness, T2H)
    answered(harness.client, asked.item_id, {"answer": KOREAN})

    seed_row, answer_row = word_detail(harness.client, asked.word_id)["history"]

    # A seed entry's full key set is pinned by test_api_vocab_words.py; an answer has the same.
    assert set(answer_row) == set(seed_row)
    assert set(answer_row) >= ANSWER_CONTEXT_KEYS
    assert seed_row["is_seed"] is True
    assert (seed_row["direction"], seed_row["mode"], seed_row["correct"]) == (None, None, None)
    assert answer_row["is_seed"] is False
    assert (answer_row["direction"], answer_row["mode"], answer_row["correct"]) == (
        T2H,
        "typing",
        True,
    )
