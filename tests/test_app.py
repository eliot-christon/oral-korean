"""Tests for the FastAPI application factory.

Write-mode note: `oral_korean` now exists (`src/oral_korean/config.py`,
`src/oral_korean/api/app.py`, `src/oral_korean/api/routes/health.py`) and every test
below runs against the real implementation, not a stub. The contract these tests pin:

- `oral_korean.config.AppConfig` - a frozen dataclass with `host: str`, `port: int`
  and `frontend_dist: Path` fields, all with sensible defaults so `AppConfig()`
  works, and all overridable via keyword arguments, e.g.
  `AppConfig(frontend_dist=tmp_path / "dist")`.
- `oral_korean.api.app.create_app(config: AppConfig) -> FastAPI` - a factory (not a
  module-level `app` object) so each test can build an isolated instance against its
  own `frontend_dist`. Calling it twice must return two distinct `FastAPI` instances.
- `GET /api/health` - `200` with a JSON object with a `status` key whose value reads
  as healthy (`"ok"`, `"healthy"` or `"up"`).
- when `frontend_dist` points at a real build (an `index.html` plus assets), `GET /`
  serves that `index.html` and the assets are reachable at their paths.
- when `frontend_dist` does not exist, building the app must not raise, and `GET /`
  must return a readable message naming the `npm run build` command instead of a bare
  404 or a stack trace.
- an unmatched path under `/api/` must 404 as JSON (never fall through to the HTML
  index).
- an unmatched path outside `/api/` must 404 too, even when a frontend build exists -
  the static/catch-all mount must not serve the index for every unknown path (that
  would break the previous requirement's contrast and mask real 404s).

One asymmetry surfaced while probing the `/api` (no trailing slash) boundary: see
`test_api_root_without_trailing_slash_returns_json_404_when_frontend_missing` below
for what it caught and how `create_app` was fixed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from conftest import FakeFrontendBuild
from fastapi.testclient import TestClient

from oral_korean.api.app import create_app
from oral_korean.config import AppConfig


def test_app_config_exposes_host_port_and_frontend_dist_with_defaults() -> None:
    """`AppConfig()` must work with no arguments and expose the three documented fields."""
    config = AppConfig()

    assert isinstance(config.host, str)
    assert isinstance(config.port, int)
    assert isinstance(config.frontend_dist, Path)


def test_app_config_accepts_host_and_port_overrides(tmp_path: Path) -> None:
    """Every documented field, not just `frontend_dist`, must be overridable by keyword."""
    config = AppConfig(host="0.0.0.0", port=9999, frontend_dist=tmp_path / "dist")

    assert config.host == "0.0.0.0"
    assert config.port == 9999
    assert config.frontend_dist == tmp_path / "dist"


def test_app_config_is_frozen() -> None:
    """`AppConfig` instances must be immutable once built.

    `create_app` is documented to build a fresh `FastAPI` app per call from a shared
    config with no module-level global state; that guarantee only holds if a config
    handed to several `create_app` calls cannot be mutated out from under them.
    """
    config = AppConfig()

    try:
        setattr(config, "port", 1234)  # noqa: B010 - exercising frozen-dataclass enforcement
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("AppConfig must reject attribute assignment")


def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    """`GET /api/health` reports the app is up, in a small deterministic JSON shape."""
    config = AppConfig(frontend_dist=tmp_path / "dist")
    client = TestClient(create_app(config))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "healthy", "up"}


def test_serves_built_frontend_index(fake_frontend_build: FakeFrontendBuild) -> None:
    """With a real build present, `GET /` serves that build's `index.html`."""
    config = AppConfig(frontend_dist=fake_frontend_build.dist_dir)
    client = TestClient(create_app(config))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert fake_frontend_build.index_marker in response.text


def test_serves_built_frontend_asset(fake_frontend_build: FakeFrontendBuild) -> None:
    """With a real build present, its hashed asset is reachable at its own path.

    The fixture's asset lives under a nested `assets/` subdirectory, so this also
    covers static serving through a subdirectory, not just files at the build root.
    """
    config = AppConfig(frontend_dist=fake_frontend_build.dist_dir)
    client = TestClient(create_app(config))

    response = client.get(fake_frontend_build.asset_url_path)

    assert response.status_code == 200
    assert response.text == fake_frontend_build.asset_content


def test_building_app_with_missing_frontend_dist_does_not_raise(tmp_path: Path) -> None:
    """A missing build directory must not blow up app construction."""
    missing_dist = tmp_path / "dist"
    assert not missing_dist.exists()
    config = AppConfig(frontend_dist=missing_dist)

    app = create_app(config)  # must not raise

    assert app is not None


def test_missing_frontend_build_names_the_build_command(tmp_path: Path) -> None:
    """`GET /` with no build present explains how to produce one, instead of 404ing bare."""
    config = AppConfig(frontend_dist=tmp_path / "dist")
    client = TestClient(create_app(config))

    response = client.get("/")

    assert "npm run build" in response.text


def test_unknown_api_path_returns_json_404(tmp_path: Path) -> None:
    """An unmatched `/api/...` path 404s as JSON, with a stable, parseable body shape."""
    config = AppConfig(frontend_dist=tmp_path / "dist")
    client = TestClient(create_app(config))

    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("detail"), str)


def test_unknown_non_api_path_returns_404_even_with_a_built_frontend(
    fake_frontend_build: FakeFrontendBuild,
) -> None:
    """An unmatched non-API path 404s; the catch-all must not serve the index for it."""
    config = AppConfig(frontend_dist=fake_frontend_build.dist_dir)
    client = TestClient(create_app(config))

    response = client.get("/nope")

    assert response.status_code == 404
    assert fake_frontend_build.index_marker not in response.text


def test_api_root_without_trailing_slash_returns_json_404_when_frontend_built(
    fake_frontend_build: FakeFrontendBuild,
) -> None:
    """`GET /api` (no trailing slash) must 404 as JSON, not serve the built frontend."""
    config = AppConfig(frontend_dist=fake_frontend_build.dist_dir)
    client = TestClient(create_app(config))

    response = client.get("/api")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert fake_frontend_build.index_marker not in response.text


def test_api_root_without_trailing_slash_returns_json_404_when_frontend_missing(
    tmp_path: Path,
) -> None:
    """`GET /api` (no trailing slash) must 404 as JSON, not the "build the frontend" HTML.

    This test caught a real bug: the path converter used for the API's catch-all
    (`/api/{_full_path:path}`) requires the literal "/" it follows, so it cannot match
    the prefix's own root - `/api` alone fell through to the app-level
    `/{_full_path:path}` catch-all and got the "npm run build" HTML message with a 200,
    instead of the JSON 404 every other `/api/...` path gets. Fixed in
    `src/oral_korean/api/app.py` by also registering the API 404 handler at the bare
    `""` path on the `/api`-prefixed router. This asymmetry never showed up for a built
    frontend, where `StaticFiles` itself 404s (see the sibling test above) - only when
    the frontend is missing and the HTML catch-all is registered directly on `app`.
    """
    config = AppConfig(frontend_dist=tmp_path / "dist")
    client = TestClient(create_app(config))

    response = client.get("/api")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_create_app_called_twice_returns_distinct_instances(tmp_path: Path) -> None:
    """The factory must not rely on module-level global state."""
    config = AppConfig(frontend_dist=tmp_path / "dist")

    first_app = create_app(config)
    second_app = create_app(config)

    assert first_app is not second_app
