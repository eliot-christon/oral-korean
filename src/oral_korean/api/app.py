"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from oral_korean.api.routes import health
from oral_korean.config import AppConfig

_BUILD_MESSAGE = (
    "<!doctype html><html><body>"
    "<p>The frontend has not been built yet. Run <code>npm run build</code> "
    "in <code>frontend/</code>, then restart the server.</p>"
    "</body></html>"
)


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Build a fresh FastAPI application instance.

    A new instance is returned on every call - nothing here is a module-level
    global, so tests can build several isolated apps against different configs.
    """
    config = config or AppConfig()
    app = FastAPI(title="oral-korean")

    api_router = APIRouter(prefix="/api")
    api_router.include_router(health.router)

    async def api_not_found(_full_path: str = "") -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    # Two routes: the path converter requires the literal "/" it follows, so it
    # cannot match the prefix's own root ("/api" with nothing after it).
    api_router.add_api_route("", api_not_found, methods=["GET"], include_in_schema=False)
    api_router.add_api_route(
        "/{_full_path:path}", api_not_found, methods=["GET"], include_in_schema=False
    )

    app.include_router(api_router)

    if (config.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=config.frontend_dist, html=True), name="frontend")
    else:

        @app.get("/{_full_path:path}", include_in_schema=False)
        async def frontend_not_built(_full_path: str) -> HTMLResponse:
            return HTMLResponse(_BUILD_MESSAGE)

    return app
