"""Tests for the vocabulary's HTTP routes: vocab-core T05, over T01 to T04.

Every route lives under `/api/vocab`. The paths and the response shapes are a contract that
`vocab-words-ui` builds on, so they are pinned here once, in the constants and helpers below:

- A **word**: `id`, `korean`, `translations` (list), `tags` (list), `familiarity`,
  `added_at`, and `statistics` at the clock's instant: `score`, `recall` (whole percents,
  null for a new word), `phase`, `stability`, `difficulty`, `next_review`, `last_review`,
  `due`, `review_count`, `lapse_count`.
- The **list**: `{"words": [...], "summary": {"total", "new", "due", "average_score"}}`.
- One word's **detail**: a word plus `history`, each entry `reviewed_at`, `grade`, `is_seed`,
  `recall_before` (a whole percent, null for a seed), `stability`, `difficulty`,
  `next_review`.
- **Adding** takes `korean`, `translations` as typed (`"house; home"`), `tags` and
  `familiarity` (default `new`); a **pasted batch** takes `text`, `tags` and `familiarity`
  and answers `{"words": [...]}`. **Editing** takes `korean`, `translations` and `tags`.
- **Refusals**: an invalid entry is `422` and a duplicate `409`, both with a string
  `detail`; a refused batch is `422` with `detail` `{"errors": [{"line", "message"}]}`,
  `line` null for a problem with the whole batch.
- **Tags**: `{"tags": [{"tag", "count"}]}`. **Familiarity**: `{"levels": [{"familiarity",
  "grade", "score", "stability", "first_review_in_days"}]}`, all but the level null for `new`.

The harness is `conftest.py`'s app-wide one: a fake speech engine, a per-test database under
`tmp_path`, and a fake clock starting at T0 = 2026-09-21 09:00 UTC. Expected FSRS figures come
from `srs/` at T0 with fuzzing off, never re-derived here: the routes seed with fuzzing on, so
the tests stay on familiarity levels whose first delay FSRS never fuzzes (`a_little`, `well`)
wherever a date is compared.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import HARNESS_START, NumbersHarness, build_numbers_harness
from fastapi.testclient import TestClient
from httpx import Response

from oral_korean.api.app import create_app
from oral_korean.config import AppConfig
from oral_korean.srs.memory import Familiarity, MemoryState, ReviewRecord, score, seed

VOCAB = "/api/vocab"
WORDS = f"{VOCAB}/words"
BATCH = f"{WORDS}/batch"
TAGS = f"{VOCAB}/tags"
FAMILIARITY = f"{VOCAB}/familiarity"

T0 = HARNESS_START

type Json = dict[str, Any]


@pytest.fixture(name="harness")
def make_harness(tmp_path: Path) -> NumbersHarness:
    """The app-wide harness (named for the numbers exercise, its first user)."""
    return build_numbers_harness(tmp_path)


@pytest.fixture(name="client")
def make_client(harness: NumbersHarness) -> TestClient:
    return harness.client


def word_path(word_id: int) -> str:
    return f"{WORDS}/{word_id}"


def seeded(familiarity: Familiarity, at: datetime = T0) -> tuple[MemoryState, ReviewRecord]:
    """What `srs/` seeds for `familiarity` at `at`, with fuzzing off."""
    result = seed(familiarity, at, fuzzing=False)
    assert result is not None, f"{familiarity} seeds nothing"
    return result


def seeded_score(familiarity: Familiarity) -> int:
    """The score `srs/` gives a word seeded with `familiarity` at T0."""
    value = score(seeded(familiarity)[0])
    assert value is not None
    return value


def instant(text: str | None) -> datetime | None:
    """A datetime from the JSON, aware as the API writes it."""
    return None if text is None else datetime.fromisoformat(text)


def add(
    client: TestClient,
    korean: str,
    translations: str = "x",
    *,
    tags: list[str] | None = None,
    familiarity: str | None = None,
) -> Response:
    body: Json = {"korean": korean, "translations": translations, "tags": tags or []}
    if familiarity is not None:
        body["familiarity"] = familiarity
    response: Response = client.post(WORDS, json=body)
    return response


def added(client: TestClient, korean: str, translations: str = "x", **kwargs: Any) -> Json:
    """Add a word that must be accepted, and return it."""
    response = add(client, korean, translations, **kwargs)
    assert response.status_code == 201, response.text
    word: Json = response.json()
    return word


def paste(
    client: TestClient, text: str, *, tags: list[str] | None = None, familiarity: str = "new"
) -> Response:
    body = {"text": text, "tags": tags or [], "familiarity": familiarity}
    response: Response = client.post(BATCH, json=body)
    return response


def listed(client: TestClient, **params: str) -> Json:
    response = client.get(WORDS, params=params)
    assert response.status_code == 200, response.text
    body: Json = response.json()
    return body


def listed_korean(client: TestClient) -> list[str]:
    return [word["korean"] for word in listed(client)["words"]]


def detail(client: TestClient, word_id: int) -> Json:
    response = client.get(word_path(word_id))
    assert response.status_code == 200, response.text
    body: Json = response.json()
    return body


# ---------------------------------------------------------------------------------
# Adding one word
# ---------------------------------------------------------------------------------


def test_adding_a_word_returns_it_new_with_an_id_and_lists_it(client: TestClient) -> None:
    """Familiarity omitted: the word is new, with nothing FSRS knows about it."""
    response = add(client, "사과", "apple", tags=["food"])

    assert response.status_code == 201
    word = response.json()
    assert isinstance(word["id"], int)
    assert word["korean"] == "사과"
    assert word["translations"] == ["apple"]
    assert word["tags"] == ["food"]
    assert word["familiarity"] == "new"
    assert instant(word["added_at"]) == T0
    assert word["statistics"] == {
        "score": None,
        "recall": None,
        "phase": "new",
        "stability": None,
        "difficulty": None,
        "next_review": None,
        "last_review": None,
        "due": False,
        "review_count": 0,
        "lapse_count": 0,
    }
    assert listed(client)["words"] == [word]


def test_adding_a_word_known_well_seeds_it(client: TestClient) -> None:
    state, record = seeded(Familiarity.WELL)

    word = added(client, "사과", "apple", familiarity="well")

    statistics = word["statistics"]
    assert word["familiarity"] == "well"
    assert statistics["score"] == score(state)
    assert statistics["recall"] == 100
    assert statistics["phase"] == "review"
    assert statistics["stability"] == state.stability
    assert statistics["difficulty"] == state.difficulty
    assert instant(statistics["next_review"]) == state.next_review
    assert instant(statistics["last_review"]) == T0
    assert statistics["due"] is False
    assert statistics["review_count"] == 0
    history = detail(client, word["id"])["history"]
    assert len(history) == 1
    assert history[0]["is_seed"] is True
    assert history[0]["grade"] == record.grade.value == "good"


def test_translations_are_split_as_typed(client: TestClient) -> None:
    word = added(client, "집", "house;  home ;")

    assert word["translations"] == ["house", "home"]


def test_an_invalid_entry_is_a_422_with_a_string_detail_and_stores_nothing(
    client: TestClient,
) -> None:
    """T03's message, as the numbers routes surface `InvalidRangeError`."""
    response = add(client, "apple", "사과")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "hangul" in response.json()["detail"].lower()
    assert listed_korean(client) == []


def test_a_duplicate_is_a_409_naming_the_stored_word_and_stores_nothing(
    client: TestClient,
) -> None:
    added(client, "사과", "apple")

    response = add(client, "사 과", "apple")

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    assert "사과" in response.json()["detail"]
    assert listed_korean(client) == ["사과"]


def test_an_unknown_familiarity_is_pydantics_422_and_stores_nothing(client: TestClient) -> None:
    response = add(client, "사과", "apple", familiarity="expert")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert listed_korean(client) == []


# ---------------------------------------------------------------------------------
# Adding a pasted batch
# ---------------------------------------------------------------------------------


def test_a_valid_paste_adds_every_word_seeded_and_tagged(client: TestClient) -> None:
    state, _ = seeded(Familiarity.A_LITTLE)

    response = paste(client, "사과 ; apple\n배 ; pear", tags=["food"], familiarity="a_little")

    assert response.status_code == 201
    words = response.json()["words"]
    assert [word["korean"] for word in words] == ["사과", "배"]
    for word in words:
        assert word["tags"] == ["food"]
        assert word["statistics"]["recall"] == 100
        assert instant(word["statistics"]["next_review"]) == state.next_review
    assert listed(client)["words"] == words


def test_a_paste_with_an_invalid_line_is_refused_whole(client: TestClient) -> None:
    response = paste(client, "사과 ; apple\napple ; pear\n배 ; pear")

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert len(errors) == 1
    assert errors[0]["line"] == 2
    assert isinstance(errors[0]["message"], str)
    assert listed_korean(client) == []


def test_a_paste_repeating_a_stored_word_names_its_line_and_stores_nothing(
    client: TestClient,
) -> None:
    added(client, "사과", "apple")

    response = paste(client, "배 ; pear\n감 ; persimmon\n사 과 ; apple")

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert [error["line"] for error in errors] == [3]
    assert "사과" in errors[0]["message"]
    assert listed_korean(client) == ["사과"]


def test_blank_lines_count_in_a_reported_line_number(client: TestClient) -> None:
    response = paste(client, "\n사과 ; apple\napple ; pear")

    assert response.status_code == 422
    assert [error["line"] for error in response.json()["detail"]["errors"]] == [3]


def test_a_problem_with_the_whole_paste_has_no_line(client: TestClient) -> None:
    response = paste(client, "\n  \n")

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert len(errors) == 1
    assert errors[0]["line"] is None


# ---------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------


def test_the_list_filters_by_tag(client: TestClient) -> None:
    added(client, "사과", "apple", tags=["food"])
    added(client, "가다", "to go", tags=["verb"])
    added(client, "배", "pear", tags=["food", "fruit"])

    assert [word["korean"] for word in listed(client, tag="food")["words"]] == ["사과", "배"]


def test_an_unknown_tag_lists_nothing_with_a_summary_of_zeros(client: TestClient) -> None:
    added(client, "사과", "apple", tags=["food"])

    body = listed(client, tag="nope")

    assert body == {
        "words": [],
        "summary": {"total": 0, "new": 0, "due": 0, "average_score": None},
    }


def test_the_summary_moves_with_the_clock(harness: NumbersHarness) -> None:
    """One new word, one known very well, one a little: only the last falls due in a day."""
    client = harness.client
    added(client, "사과", "apple")
    added(client, "배", "pear", familiarity="very_well")
    little = added(client, "감", "persimmon", familiarity="a_little")

    at_t0 = listed(client)["summary"]
    harness.clock.advance(timedelta(days=1))
    a_day_later = listed(client)

    assert at_t0["total"] == 3
    assert at_t0["new"] == 1
    assert at_t0["due"] == 0
    assert a_day_later["summary"]["due"] == 1
    (little_later,) = [word for word in a_day_later["words"] if word["id"] == little["id"]]
    assert little_later["statistics"]["due"] is True
    assert little_later["statistics"]["recall"] < 100
    assert little_later["statistics"]["score"] == little["statistics"]["score"]


def test_the_average_score_ignores_new_words(client: TestClient) -> None:
    added(client, "사과", "apple")
    assert listed(client)["summary"]["average_score"] is None

    added(client, "배", "pear", familiarity="very_well")
    added(client, "감", "persimmon", familiarity="a_little")

    scores = [seeded_score(level) for level in (Familiarity.VERY_WELL, Familiarity.A_LITTLE)]
    assert listed(client)["summary"]["average_score"] == round(sum(scores) / len(scores))


def test_one_word_comes_with_its_statistics_and_history(client: TestClient) -> None:
    state, record = seeded(Familiarity.WELL)
    word = added(client, "사과", "apple", familiarity="well")

    body = detail(client, word["id"])

    assert {key: value for key, value in body.items() if key != "history"} == word
    assert body["history"] == [
        {
            "reviewed_at": body["history"][0]["reviewed_at"],
            "grade": "good",
            "is_seed": True,
            "recall_before": None,
            "stability": record.stability,
            "difficulty": record.difficulty,
            "next_review": body["history"][0]["next_review"],
        }
    ]
    assert instant(body["history"][0]["reviewed_at"]) == T0
    assert instant(body["history"][0]["next_review"]) == state.next_review


def test_a_new_word_has_no_history(client: TestClient) -> None:
    word = added(client, "사과", "apple")

    assert detail(client, word["id"])["history"] == []


def test_an_unknown_word_is_a_json_404(client: TestClient) -> None:
    response = client.get(word_path(999))

    assert response.status_code == 404
    assert "detail" in response.json()


# ---------------------------------------------------------------------------------
# Statistics over time
# ---------------------------------------------------------------------------------


def test_recall_decays_while_the_score_stays(harness: NumbersHarness) -> None:
    word = added(harness.client, "사과", "apple", familiarity="well")
    assert word["statistics"]["recall"] == 100

    harness.clock.advance(timedelta(days=7))
    later = detail(harness.client, word["id"])["statistics"]

    assert later["recall"] < 100
    assert later["score"] == word["statistics"]["score"]
    assert later["due"] is True


# ---------------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------------


def edit(
    client: TestClient, word_id: int, korean: str, translations: str, tags: list[str]
) -> Response:
    body = {"korean": korean, "translations": translations, "tags": tags}
    response: Response = client.put(word_path(word_id), json=body)
    return response


def test_editing_changes_the_text_and_keeps_the_memory(client: TestClient) -> None:
    word = added(client, "사과", "apple", tags=["food"], familiarity="well")
    before = detail(client, word["id"])

    response = edit(client, word["id"], "배", "pear; ship", ["fruit"])

    assert response.status_code == 200
    after = response.json()
    assert after["korean"] == "배"
    assert after["translations"] == ["pear", "ship"]
    assert after["tags"] == ["fruit"]
    assert after["familiarity"] == "well"
    assert after["added_at"] == before["added_at"]
    assert after["statistics"] == before["statistics"]
    assert detail(client, word["id"])["history"] == before["history"]


def test_editing_onto_another_words_korean_is_a_409_and_changes_nothing(
    client: TestClient,
) -> None:
    apple = added(client, "사과", "apple")
    pear = added(client, "배", "pear")

    response = edit(client, pear["id"], "사 과", "apple", [])

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    assert "사과" in response.json()["detail"]
    assert listed(client)["words"] == [apple, pear]


def test_editing_an_unknown_word_is_a_404(client: TestClient) -> None:
    response = edit(client, 999, "사과", "apple", [])

    assert response.status_code == 404
    assert listed_korean(client) == []


def test_an_unknown_word_is_a_404_before_its_new_content_is_judged(client: TestClient) -> None:
    """There is nothing to edit, so what the edit would have said does not matter."""
    response = edit(client, 999, "apple", " ; ", [])

    assert response.status_code == 404


def test_an_invalid_edit_is_a_422_and_changes_nothing(client: TestClient) -> None:
    word = added(client, "사과", "apple")

    response = edit(client, word["id"], "사과", " ; ", [])

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert detail(client, word["id"])["translations"] == ["apple"]


# ---------------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------------


def test_deleting_a_word_removes_it_and_its_tag_count(client: TestClient) -> None:
    word = added(client, "사과", "apple", tags=["food"], familiarity="well")
    added(client, "배", "pear", tags=["fruit"])

    response = client.delete(word_path(word["id"]))

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(word_path(word["id"])).status_code == 404
    assert client.get(TAGS).json() == {"tags": [{"tag": "fruit", "count": 1}]}


def test_deleting_an_unknown_word_is_a_404(client: TestClient) -> None:
    response = client.delete(word_path(999))

    assert response.status_code == 404
    assert "detail" in response.json()


# ---------------------------------------------------------------------------------
# Tags and familiarity
# ---------------------------------------------------------------------------------


def test_tags_come_with_their_word_counts_sorted(client: TestClient) -> None:
    added(client, "배", "pear", tags=["food", "fruit"])
    added(client, "사과", "apple", tags=["food"])
    added(client, "가다", "to go", tags=["verb"])

    response = client.get(TAGS)

    assert response.status_code == 200
    assert response.json() == {
        "tags": [
            {"tag": "food", "count": 2},
            {"tag": "fruit", "count": 1},
            {"tag": "verb", "count": 1},
        ]
    }


def test_the_familiarity_catalogue_reports_what_each_level_seeds(client: TestClient) -> None:
    """Computed through `srs/`, so the UI never hardcodes "8 days"."""
    response = client.get(FAMILIARITY)

    assert response.status_code == 200
    levels = response.json()["levels"]
    assert [level["familiarity"] for level in levels] == [
        "new",
        "a_little",
        "well",
        "very_well",
    ]
    assert levels[0] == {
        "familiarity": "new",
        "grade": None,
        "score": None,
        "stability": None,
        "first_review_in_days": None,
    }
    for level in levels[1:]:
        state, record = seeded(Familiarity(level["familiarity"]))
        assert level["grade"] == record.grade.value
        assert level["score"] == score(state)
        assert level["stability"] == state.stability
        assert level["first_review_in_days"] == (state.next_review - T0).days
    delays = [level["first_review_in_days"] for level in levels[1:]]
    assert delays == sorted(set(delays))


# ---------------------------------------------------------------------------------
# Isolation and wiring
# ---------------------------------------------------------------------------------


def test_the_database_is_created_by_the_first_vocab_request(harness: NumbersHarness) -> None:
    database_path = harness.config.database_path
    assert not database_path.exists()
    assert not database_path.parent.exists()

    listed(harness.client)

    assert database_path.is_file()


def test_two_apps_on_two_databases_do_not_share_words(tmp_path: Path) -> None:
    first = build_numbers_harness(tmp_path / "first")
    second = build_numbers_harness(tmp_path / "second")

    added(first.client, "사과", "apple")

    assert listed_korean(first.client) == ["사과"]
    assert listed_korean(second.client) == []


def test_an_unknown_vocab_path_is_still_a_json_404(client: TestClient) -> None:
    response = client.get(f"{VOCAB}/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_the_default_clock_is_the_aware_current_time(tmp_path: Path) -> None:
    """Built without a clock, the app stamps words with the real UTC instant."""
    config = AppConfig(
        frontend_dist=tmp_path / "dist", database_path=tmp_path / "vocabulary.sqlite3"
    )
    client = TestClient(create_app(config))

    before = datetime.now(UTC)
    word = added(client, "사과", "apple")
    after = datetime.now(UTC)

    added_at = instant(word["added_at"])
    assert added_at is not None
    assert before <= added_at <= after
