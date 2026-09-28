"""Pending items keyed by an opaque id, shared by every exercise route.

An exercise route hands the browser an id instead of the answer itself; the item stays on
the server, in a plain `dict` the route already owns (`app.state.number_questions`,
`app.state.vocab_items`), under a fresh `secrets.token_urlsafe(16)` id. These functions
store, look up and take, generic over the item type so every exercise's own dict works
unchanged - `numbers.py`'s
`dict[str, NumberQuestion]` stays exactly that, never wrapped in a class.

Numbers questions are looked up and never consumed; a vocab question is **taken**, so it
is scored at most once: `dict.pop` is atomic, so of two answers racing for one id exactly
one gets the item.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException


def store_pending[T](store: dict[str, T], item: T) -> str:
    """Store `item` under a fresh opaque id in `store` (mutated in place), and return it."""
    item_id = secrets.token_urlsafe(16)
    store[item_id] = item
    return item_id


def get_pending_or_404[T](store: dict[str, T], item_id: str) -> T:
    """Look `item_id` up in `store` without consuming it, or raise a 404 naming it."""
    item = store.get(item_id)
    if item is None:
        raise _not_found(item_id)
    return item


def take_pending_or_404[T](store: dict[str, T], item_id: str) -> T:
    """Remove `item_id` from `store` and return its item, or raise a 404 naming it."""
    item = store.pop(item_id, None)
    if item is None:
        raise _not_found(item_id)
    return item


def _not_found(item_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No item with id {item_id!r}.")
