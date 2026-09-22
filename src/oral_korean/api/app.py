"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from oral_korean.api.routes import health, numbers, vocab_words
from oral_korean.config import AppConfig
from oral_korean.exercises.numbers import NumberQuestion
from oral_korean.storage.database import Database
from oral_korean.storage.words import WordStore
from oral_korean.tts.base import SpeechEngine
from oral_korean.tts.cache import AudioCache
from oral_korean.tts.melo_engine import MeloSpeechEngine

_BUILD_MESSAGE = (
    "<!doctype html><html><body>"
    "<p>The frontend has not been built yet. Run <code>npm run build</code> "
    "in <code>frontend/</code>, then restart the server.</p>"
    "</body></html>"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    config: AppConfig | None = None,
    *,
    speech_engine: SpeechEngine | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build a fresh FastAPI application instance.

    A new instance is returned on every call - nothing here is a module-level
    global, so tests can build several isolated apps against different configs.

    Args:
        config: runtime configuration; `None` builds the default `AppConfig()`.
        speech_engine: the engine behind the audio cache. `None` builds a
            `MeloSpeechEngine`, which is free to construct - tests inject a fake here so
            no route ever loads MeloTTS.
        clock: returns the current instant, timezone-aware, for everything the vocabulary
            dates or reads at a moment in time. `None` reads the real UTC time - tests
            inject a clock they can move, so every statistic is checked at a known instant.
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
    # Opens nothing: the file, its directory and its schema come with the first vocab request.
    app.state.word_store = WordStore(Database(config.database_path))
    app.state.clock = clock if clock is not None else _utc_now

    api_router = APIRouter(prefix="/api")
    api_router.include_router(health.router)
    api_router.include_router(numbers.router)
    api_router.include_router(vocab_words.router)

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
