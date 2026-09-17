"""Shared fixtures for the oral_korean test suite."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

# Content markers used to prove *which* file the app actually served, without
# the test re-implementing any HTML/JS parsing of its own.
INDEX_MARKER = "FAKE_FRONTEND_INDEX_MARKER"
ASSET_CONTENT = "console.log('FAKE_FRONTEND_ASSET_MARKER');"
ASSET_RELATIVE_PATH = "assets/index-abc123.js"


@dataclass(frozen=True)
class FakeFrontendBuild:
    """A minimal fake `frontend/dist/` build for exercising static serving.

    Attributes:
        dist_dir: the fake build directory, suitable for `AppConfig(frontend_dist=...)`.
        index_marker: a string expected to appear in the served index page's body.
        asset_url_path: the URL path (starting with "/") at which the asset should be
            reachable once the app serves `dist_dir`.
        asset_content: the exact body expected when fetching `asset_url_path`.
    """

    dist_dir: Path
    index_marker: str
    asset_url_path: str
    asset_content: str


@pytest.fixture
def fake_frontend_build(tmp_path: Path) -> FakeFrontendBuild:
    """Create a fresh fake `dist/` directory with an `index.html` and one asset.

    A fresh directory is created per call (never a shared mutable fixture), so tests
    cannot leak state into one another via the filesystem.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text(
        f"<!doctype html><html><body>{INDEX_MARKER}</body></html>",
        encoding="utf-8",
    )

    asset_path = dist_dir / ASSET_RELATIVE_PATH
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text(ASSET_CONTENT, encoding="utf-8")

    return FakeFrontendBuild(
        dist_dir=dist_dir,
        index_marker=INDEX_MARKER,
        asset_url_path=f"/{ASSET_RELATIVE_PATH}",
        asset_content=ASSET_CONTENT,
    )
