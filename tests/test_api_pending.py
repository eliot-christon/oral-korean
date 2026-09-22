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

Both are generic over the item type and take the store as a plain argument rather than a
`Request`: neither function needs a `FastAPI` app to test, which is the point of testing
them "over a plain dict" (the ticket's own phrase) instead of through HTTP. The consuming
"take" variant (`vocab-sessions` T03) is deliberately absent from both the implementation
and this file: numbers never consumes a question, so a take helper would be exercised by
tests alone at this point, which is exactly the dead code the ticket calls out.

`get_pending_or_404` raising a plain `HTTPException` is enough to pin the "JSON 404"
acceptance criterion without building an app: FastAPI turns any uncaught `HTTPException`
into a JSON body of that shape for every route in the project already (see the 404 tests
in `test_api_numbers.py`, unmodified by this ticket), so re-proving the JSON envelope here
over a toy two-route app would only duplicate that coverage instead of adding any.
"""

from __future__ import annotations

import re

import pytest
from fastapi import HTTPException

from oral_korean.api.pending import get_pending_or_404, store_pending

URL_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
MINIMUM_ID_LENGTH = 16


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
