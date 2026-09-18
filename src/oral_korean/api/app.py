"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from oral_korean.api.routes import health, numbers
from oral_korean.config import AppConfig
from oral_korean.exercises.numbers import NumberQuestion
from oral_korean.tts.base import SpeechEngine
from oral_korean.tts.cache import AudioCache
from oral_korean.tts.melo_engine import MeloSpeechEngine

_BUILD_MESSAGE = (
    "<!doctype html><html><body>"
    "<p>The frontend has not been built yet. Run <code>npm run build</code> "
    "in <code>frontend/</code>, then restart the server.</p>"
    "</body></html>"
)


def create_app(
    config: AppConfig | None = None, *, speech_engine: SpeechEngine | None = None
) -> FastAPI:
    """Build a fresh FastAPI application instance.

    A new instance is returned on every call - nothing here is a module-level
    global, so tests can build several isolated apps against different configs.

    Args:
        config: runtime configuration; `None` builds the default `AppConfig()`.
        speech_engine: the engine behind the audio cache. `None` builds a
            `MeloSpeechEngine`, which is free to construct - tests inject a fake here so
            no route ever loads MeloTTS.
    """
    config = config or AppConfig()
    engine = speech_engine if speech_engine is not None else MeloSpeechEngine()
    app = FastAPI(title="oral-korean")

    number_questions: dict[str, NumberQuestion] = {}
    app.state.number_questions = number_questions
    app.state.audio_cache = AudioCache(
        engine,
        cache_dir=config.audio_cache_dir,
        voice=config.tts_voice,
        speed=config.tts_speed,
    )

    api_router = APIRouter(prefix="/api")
    api_router.include_router(health.router)
    api_router.include_router(numbers.router)

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
