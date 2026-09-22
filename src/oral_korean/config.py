"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_host() -> str:
    """Return the interface to bind, loopback unless the environment says otherwise.

    A container has to bind every interface to be reachable from the host, while a plain
    `uv run main.py` on a laptop should stay off the network. The default is therefore the
    safe one and the container opts out.
    """
    return os.environ.get("ORAL_KOREAN_HOST", "127.0.0.1")


def _default_port() -> int:
    return int(os.environ.get("ORAL_KOREAN_PORT", "8000"))


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_frontend_dist() -> Path:
    return _PROJECT_ROOT / "frontend" / "dist"


def _default_audio_cache_dir() -> Path:
    # Under `.cache/`, which `.gitignore` already covers as a runtime cache.
    return _PROJECT_ROOT / ".cache" / "audio"


def _default_database_path() -> Path:
    """Return where the vocabulary lives, `.data/` unless the environment says otherwise.

    `.data/`, not `.cache/`: a cache is something the user may delete to reclaim space, and
    this file is their vocabulary. The environment variable is how the test suite keeps
    every test away from the real file, and the hook a later deployment needs.
    """
    configured = os.environ.get("ORAL_KOREAN_DATABASE_PATH")
    if configured:
        return Path(configured)
    return _PROJECT_ROOT / ".data" / "oral-korean.sqlite3"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for the FastAPI app and its dev server."""

    host: str = field(default_factory=_default_host)
    port: int = field(default_factory=_default_port)
    frontend_dist: Path = field(default_factory=_default_frontend_dist)
    audio_cache_dir: Path = field(default_factory=_default_audio_cache_dir)
    database_path: Path = field(default_factory=_default_database_path)
    tts_voice: str = "KR"
    tts_speed: float = 1.0
