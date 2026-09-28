"""Tests for choosing a session's words over HTTP: vocab-directions T03.

Written before the implementation, in their own file for pylint's module length
(`test_api_vocab_sessions.py` is close to it). The routes, all under `/api/vocab`:

- `GET /learn-queue?tag=&directions=...` -> `{"words": [{"id", "korean", "translations",
  "tags"}]}`: the learnable words (a ticked direction without memory; all four by default),
  in the order the user set.
- `PUT /learn-queue`, body `{"word_ids": [...]}`: those words go to the top in that order,
  the others keep their order after them; `200` with the whole queue. `422` for an unknown or
  repeated id or a word learned in every direction, the queue unchanged.
- `GET /review-candidates?tag=&directions=...` -> `{"words": [{"id", "korean",
  "translations", "tags", "due", "next_review"}]}`: every word with a learned ticked
  direction, the due ones first (most overdue first), then the others (soonest first);
  `next_review` is the earliest ticked learned one.
- `POST /sessions` also takes an ordered `"word_ids"`. A review takes its first `size` ids,
  a word with nothing due reviewed early in every ticked learned direction. `422` for an
  unknown or repeated id, or a word with no learned ticked direction; `word_ids` on a learn
  start is a `422` too. Without it, a review picks its words as before.

Every refusal's detail names ids at most, never a word's Korean or translation.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Final

import pytest
from conftest import (
    H2T,
    HARNESS_START,
    SESSIONS,
    V2H,
    VOCAB,
    Json,
    NumbersHarness,
    add_word,
    instant,
    start_session,
    started,
    walk,
)

from oral_korean.exercises.vocab import AnswerMode, Direction
from oral_korean.srs.memory import Grade, apply_grade
from oral_korean.storage.words import AnswerContext, WordStore

QUEUE: Final = f"{VOCAB}/learn-queue"
CANDIDATES: Final = f"{VOCAB}/review-candidates"
DAY: Final = timedelta(days=1)
WORD_KEYS: Final = {"id", "korean", "translations", "tags"}
CANDIDATE_KEYS: Final = WORD_KEYS | {"due", "next_review"}
TEXTS: Final = ("사과", "apple", "배", "pear", "감", "persimmon", "포도", "grape")


def three_new_words(harness: NumbersHarness) -> tuple[int, int, int]:
    """사과, 배 and 감 added as new, in that order; their ids."""
    client = harness.client
    return (
        add_word(client, "사과", "apple")["id"],
        add_word(client, "배", "pear")["id"],
        add_word(client, "감", "persimmon")["id"],
    )


def queue_ids(harness: NumbersHarness, **params: object) -> list[int]:
    response = harness.client.get(QUEUE, params=params)
    assert response.status_code == 200, response.text
    body: Json = response.json()
    assert all(set(entry) == WORD_KEYS for entry in body["words"])
    return [entry["id"] for entry in body["words"]]


def reorder(harness: NumbersHarness, word_ids: list[int]) -> Json:
    response = harness.client.put(QUEUE, json={"word_ids": word_ids})
    assert response.status_code == 200, response.text
    body: Json = response.json()
    return body


def candidates(harness: NumbersHarness, **params: object) -> list[Json]:
    response = harness.client.get(CANDIDATES, params=params)
    assert response.status_code == 200, response.text
    words: list[Json] = response.json()["words"]
    assert all(set(entry) == CANDIDATE_KEYS for entry in words)
    return words


def asked_words(harness: NumbersHarness, session_id: str) -> tuple[set[str], int]:
    """The prompts of every scored question of a session walked with "I don't know", and how
    many scored questions there were. Sessions here tick `hangul_to_translation` only, whose
    prompt is the word's Korean."""
    items = walk(harness.client, session_id, {"dont_know": True})
    scored = [item for item in items if item["type"] == "question" and item["scored"]]
    return {item["prompt"] for item in scored}, len(scored)


def learn_one_way(harness: NumbersHarness, word_id: int, direction: str) -> None:
    """Give `word_id` a memory in `direction` alone, answered right by choice now, through the
    app's own store: sessions would ask every new word, and only the memory matters here."""
    store: WordStore = harness.app.state.word_store
    state, record = apply_grade(None, Grade.HARD, harness.clock.now, fuzzing=False)
    context = AnswerContext(direction=Direction(direction), mode=AnswerMode.CHOICE, correct=True)
    assert store.record_answer(word_id, state, record, context)


def assert_names_no_word(detail: object) -> None:
    text = json.dumps(detail, ensure_ascii=False)
    assert not any(word in text for word in TEXTS), text


# ---------------------------------------------------------------------------------
# The learn queue
# ---------------------------------------------------------------------------------


def test_the_queue_lists_new_words_in_the_order_they_were_added(
    numbers_harness: NumbersHarness,
) -> None:
    a, b, c = three_new_words(numbers_harness)
    add_word(numbers_harness.client, "포도", "grape", familiarity="well")

    assert queue_ids(numbers_harness) == [a, b, c]


def test_a_reorder_moves_the_words_to_the_top_and_answers_with_the_queue(
    numbers_harness: NumbersHarness,
) -> None:
    a, b, c = three_new_words(numbers_harness)

    body = reorder(numbers_harness, [c])

    assert [entry["id"] for entry in body["words"]] == [c, a, b]
    assert queue_ids(numbers_harness) == [c, a, b]


def test_the_queue_filters_by_tag_and_by_direction(numbers_harness: NumbersHarness) -> None:
    client = numbers_harness.client
    fruit = add_word(client, "사과", "apple", tags=["fruit"])["id"]
    other = add_word(client, "배", "pear")["id"]
    learn_one_way(numbers_harness, fruit, H2T)
    learn_one_way(numbers_harness, other, H2T)

    assert queue_ids(numbers_harness, tag="fruit") == [fruit]
    assert queue_ids(numbers_harness, directions=[H2T]) == []


def test_a_learn_session_takes_the_top_of_the_queue(numbers_harness: NumbersHarness) -> None:
    a, _, c = three_new_words(numbers_harness)
    reorder(numbers_harness, [c])
    assert queue_ids(numbers_harness)[:2] == [c, a]

    session_id = started(numbers_harness.client, "learn", directions=[H2T], size=2)
    prompts, count = asked_words(numbers_harness, session_id)

    assert prompts == {"감", "사과"}
    assert count == 2


@pytest.mark.parametrize("case", ["unknown", "repeated", "learned"])
def test_a_refused_reorder_is_a_422_that_leaves_the_queue_alone(
    numbers_harness: NumbersHarness, case: str
) -> None:
    a, b, c = three_new_words(numbers_harness)
    learned = add_word(numbers_harness.client, "포도", "grape", familiarity="well")["id"]
    word_ids = {"unknown": [a, learned + 100], "repeated": [b, b], "learned": [learned]}[case]

    response = numbers_harness.client.put(QUEUE, json={"word_ids": word_ids})

    assert response.status_code == 422, response.text
    assert_names_no_word(response.json()["detail"])
    assert queue_ids(numbers_harness) == [a, b, c]


# ---------------------------------------------------------------------------------
# Review candidates
# ---------------------------------------------------------------------------------


def test_review_candidates_are_overdue_then_due_then_not_due(
    numbers_harness: NumbersHarness,
) -> None:
    """Three words seeded `a_little` (due after one day), `well` (two) and `very_well`
    (eight), looked at two days in: the first is overdue, the second due, the third not."""
    client = numbers_harness.client
    overdue = add_word(client, "사과", "apple", familiarity="a_little")["id"]
    due = add_word(client, "배", "pear", familiarity="well")["id"]
    later = add_word(client, "감", "persimmon", familiarity="very_well")["id"]
    add_word(client, "포도", "grape")
    numbers_harness.clock.advance(2 * DAY)

    words = candidates(numbers_harness)

    assert [entry["id"] for entry in words] == [overdue, due, later]
    assert [entry["due"] for entry in words] == [True, True, False]
    reviews = [instant(entry["next_review"]) for entry in words]
    assert reviews == sorted(reviews)
    assert reviews[1] <= HARNESS_START + 2 * DAY < reviews[2]


def test_review_candidates_only_count_the_ticked_directions(
    numbers_harness: NumbersHarness,
) -> None:
    client = numbers_harness.client
    one_way = add_word(client, "사과", "apple")["id"]
    add_word(client, "배", "pear", tags=["fruit"])
    learn_one_way(numbers_harness, one_way, V2H)

    assert [entry["id"] for entry in candidates(numbers_harness, directions=[V2H])] == [one_way]
    assert candidates(numbers_harness, directions=[H2T]) == []
    assert candidates(numbers_harness, tag="fruit") == []


# ---------------------------------------------------------------------------------
# A review over the words chosen
# ---------------------------------------------------------------------------------


def test_a_review_over_chosen_words_takes_the_first_size_of_them(
    numbers_harness: NumbersHarness,
) -> None:
    """Y is seeded at T0 and due a day later; X is learned one way at that point, so not due.
    Asked for X then Y, size 1: X alone, early, in its one learned direction."""
    client = numbers_harness.client
    x = add_word(client, "사과", "apple")["id"]
    y = add_word(client, "배", "pear", familiarity="a_little")["id"]
    numbers_harness.clock.advance(DAY)
    learn_one_way(numbers_harness, x, H2T)
    assert [entry["due"] for entry in candidates(numbers_harness)] == [True, False]

    response = start_session(
        client, "review", word_ids=[x, y], size=1, directions=[H2T, V2H]
    )
    assert response.status_code == 201, response.text
    assert response.json()["word_count"] == 1
    prompts, count = asked_words(numbers_harness, response.json()["session_id"])

    assert prompts == {"사과"}
    assert count == 1


@pytest.mark.parametrize("case", ["unknown", "repeated", "unlearned", "learn"])
def test_a_refused_chosen_batch_is_a_422_naming_no_word(
    numbers_harness: NumbersHarness, case: str
) -> None:
    client = numbers_harness.client
    learned = add_word(client, "사과", "apple", familiarity="well")["id"]
    new = add_word(client, "배", "pear")["id"]
    kind, word_ids = {
        "unknown": ("review", [learned, new + 100]),
        "repeated": ("review", [learned, learned]),
        "unlearned": ("review", [learned, new]),
        "learn": ("learn", [new]),
    }[case]

    response = start_session(client, kind, word_ids=word_ids)

    assert response.status_code == 422, response.text
    assert_names_no_word(response.json()["detail"])
    assert not numbers_harness.app.state.vocab_sessions


def test_a_review_without_chosen_words_picks_the_due_ones_as_before(
    numbers_harness: NumbersHarness,
) -> None:
    client = numbers_harness.client
    add_word(client, "사과", "apple", familiarity="a_little")
    add_word(client, "배", "pear", familiarity="very_well")
    add_word(client, "감", "persimmon")
    numbers_harness.clock.advance(DAY)

    response = client.post(SESSIONS, json={"kind": "review", "directions": [H2T]})
    assert response.status_code == 201, response.text
    prompts, _ = asked_words(numbers_harness, response.json()["session_id"])

    assert prompts == {"사과"}
