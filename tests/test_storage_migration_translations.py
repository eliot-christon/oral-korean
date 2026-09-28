"""Tests for migration 5: translations separated by commas (2026-09-28).

A file at version 4 is built by `Database(path, migrations=MIGRATIONS[:4])` and filled with raw
SQL, since the code no longer writes version 4. Each stored translation is cut at every `,` or
`;` outside parentheses, trimmed, blanks and case-insensitive repeats dropped, order kept.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from oral_korean.korean import hangul
from oral_korean.storage.database import MIGRATIONS, Database
from oral_korean.storage.words import WordStore


def stored_at_version_4(tmp_path: Path, translations: list[str]) -> tuple[Path, int]:
    """A version-4 file holding one word with `translations`, and that word's id."""
    path = tmp_path / "oral-korean.sqlite3"
    with Database(path, migrations=MIGRATIONS[:4]).transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO words (korean, match_key, translations, familiarity, added_at) "
            "VALUES (?, ?, ?, 'new', '2026-09-01T00:00:00.000000+00:00')",
            ("쥐", hangul.match_key("쥐"), json.dumps(translations, ensure_ascii=False)),
        )
        word_id = cursor.lastrowid
    assert word_id is not None
    return path, word_id


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param(["rat, mouse"], ("rat", "mouse"), id="one-comma-separated"),
        pytest.param(["bag", "backpack"], ("bag", "backpack"), id="already-split"),
        pytest.param(
            ["fun (short form), interesting (short form)"],
            ("fun (short form)", "interesting (short form)"),
            id="parentheses-kept",
        ),
        pytest.param(
            ["to want (a thing, a person)"],
            ("to want (a thing, a person)",),
            id="comma-inside-parentheses",
        ),
        pytest.param(["house, home", "Home", "hut; "], ("house", "home", "hut"), id="repeats"),
    ],
)
def test_the_migration_splits_stored_translations(
    tmp_path: Path, before: list[str], after: tuple[str, ...]
) -> None:
    path, word_id = stored_at_version_4(tmp_path, before)

    word = WordStore(Database(path)).get_word(word_id)

    assert word is not None
    assert word.translations == after
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS) == 5
