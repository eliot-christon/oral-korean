"""Tests for `api/pending.py`: opaque-id storage shared by every exercise route.

`vocab-sessions` T01 extracts the numbers route's private `secrets.token_urlsafe(16)` +
plain-dict + `_get_question_or_404` trio into plain functions any exercise can call over
its own `dict[str, Item]`. This file is the contract those functions are written against,
and it predates the implementation, per `epic.md`'s "What the second exercise reveals":

- `store_pending(store: dict[str, T], item: T) -> str` - generates a fresh
  `secrets.token_urlsafe(16)` id, stores `item` under it in `store` (mutated in place, the
  same dict the caller already holds - `app.state.number_questions` stays a plain dict,
  never wrapped in a class), and returns the id.
- `get_pending_or_404(store: dict[str, T], item_id: str) -> T` - returns the stored item
  without removing it, or raises `fastapi.HTTPException(status_code=404, detail=...)`
  whose detail names `item_id`, exactly like today's `_get_question_or_404`.

- `take_pending_or_404(store: dict[str, T], item_id: str) -> T` (`vocab-sessions` T03, which
  brings its only caller: a vocab question is consumed by its answer) - removes and returns
  the stored item in one atomic `dict.pop`, or raises the same 404 as the lookup. Two
  threads taking one id at once must never both get it: that is what scores a double
  submission once.

All three are generic over the item type and take the store as a plain argument rather than
a `Request`: none needs a `FastAPI` app to test, which is the point of testing them "over a
plain dict" (T01's own phrase) instead of through HTTP.

`get_pending_or_404` (and the take) raising a plain `HTTPException` is enough to pin the "JSON 404"
acceptance criterion without building an app: FastAPI turns any uncaught `HTTPException`
into a JSON body of that shape for every route in the project already (see the 404 tests
in `test_api_numbers.py`, unmodified by this ticket), so re-proving the JSON envelope here
over a toy two-route app would only duplicate that coverage instead of adding any.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from oral_korean.api.pending import get_pending_or_404, store_pending, take_pending_or_404

URL_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
MINIMUM_ID_LENGTH = 16
TAKE_RACE_REPETITIONS = 20
BARRIER_TIMEOUT_SECONDS = 5.0


def test_storing_two_items_yields_two_distinct_url_safe_ids_each_retrievable() -> None:
    """Two `store_pending` calls never collide, and each id is a usable path segment."""
    store: dict[str, str] = {}

    first_id = store_pending(store, "first item")
    second_id = store_pending(store, "second item")

    assert first_id != second_id
    for item_id in (first_id, second_id):
        assert URL_SAFE_ID.fullmatch(item_id), item_id
        assert len(item_id) >= MINIMUM_ID_LENGTH

    assert get_pending_or_404(store, first_id) == "first item"
    assert get_pending_or_404(store, second_id) == "second item"


def test_looking_up_an_id_twice_returns_the_same_item_and_leaves_it_stored() -> None:
    """A lookup never consumes: the numbers exercise answers the same question twice."""
    store: dict[str, str] = {}
    item_id = store_pending(store, "an item")

    first_lookup = get_pending_or_404(store, item_id)
    second_lookup = get_pending_or_404(store, item_id)

    assert first_lookup == "an item"
    assert second_lookup == "an item"
    assert item_id in store
    assert store[item_id] == "an item"


def test_unknown_id_raises_404_naming_the_id() -> None:
    """An id nothing ever stored is a 404 whose detail names the id, not a `KeyError`."""
    store: dict[str, str] = {}

    with pytest.raises(HTTPException) as exc_info:
        get_pending_or_404(store, "does-not-exist")

    assert exc_info.value.status_code == 404
    assert "does-not-exist" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------------
# The consuming take (vocab-sessions T03)
# ---------------------------------------------------------------------------------


def test_taking_an_id_returns_the_item_and_removes_it_from_the_store() -> None:
    """A take hands the item over once: the store no longer holds it, nor answers for it."""
    store: dict[str, str] = {}
    item_id = store_pending(store, "an item")
    other_id = store_pending(store, "another item")

    taken = take_pending_or_404(store, item_id)

    assert taken == "an item"
    assert item_id not in store
    assert store == {other_id: "another item"}
    with pytest.raises(HTTPException) as exc_info:
        get_pending_or_404(store, item_id)
    assert exc_info.value.status_code == 404


def test_taking_the_same_id_twice_is_a_404_naming_it() -> None:
    """The second take is what a second answer to one vocab question runs into."""
    store: dict[str, str] = {}
    item_id = store_pending(store, "an item")
    take_pending_or_404(store, item_id)

    with pytest.raises(HTTPException) as exc_info:
        take_pending_or_404(store, item_id)

    assert exc_info.value.status_code == 404
    assert item_id in str(exc_info.value.detail)


def test_taking_an_unknown_id_is_a_404_naming_it_and_leaves_the_store_alone() -> None:
    """The same refusal as the lookup's, and nothing else in the store is touched."""
    store: dict[str, str] = {}
    kept_id = store_pending(store, "kept")

    with pytest.raises(HTTPException) as exc_info:
        take_pending_or_404(store, "does-not-exist")

    assert exc_info.value.status_code == 404
    assert "does-not-exist" in str(exc_info.value.detail)
    assert store == {kept_id: "kept"}


def test_the_take_404_is_the_same_as_the_lookup_404() -> None:
    """One refusal for "no such item", whichever helper a route called."""
    store: dict[str, str] = {}

    with pytest.raises(HTTPException) as looked_up:
        get_pending_or_404(store, "missing-id")
    with pytest.raises(HTTPException) as taken:
        take_pending_or_404(store, "missing-id")

    assert taken.value.status_code == looked_up.value.status_code
    assert taken.value.detail == looked_up.value.detail


def _take_or_none(store: dict[str, str], item_id: str, barrier: threading.Barrier) -> str | None:
    """Wait for the other thread, then take `item_id`; `None` for the one refused."""
    barrier.wait()
    try:
        return take_pending_or_404(store, item_id)
    except HTTPException:
        return None


@pytest.mark.parametrize("repetition", range(TAKE_RACE_REPETITIONS))
def test_two_threads_taking_the_same_id_at_once_only_one_gets_it(repetition: int) -> None:
    """A get-then-delete would hand the item to both; one atomic pop hands it to one."""
    store: dict[str, str] = {}
    item = f"item {repetition}"
    item_id = store_pending(store, item)
    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT_SECONDS)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_take_or_none, store, item_id, barrier) for _ in range(2)]
        results = [future.result() for future in futures]

    assert results.count(item) == 1
    assert results.count(None) == 1
    assert not store
