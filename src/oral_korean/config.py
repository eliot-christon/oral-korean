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


def _default_frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _default_audio_cache_dir() -> Path:
    # Under `.cache/`, which `.gitignore` already covers as a runtime cache.
    return Path(__file__).resolve().parents[2] / ".cache" / "audio"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for the FastAPI app and its dev server."""

    host: str = field(default_factory=_default_host)
    port: int = field(default_factory=_default_port)
    frontend_dist: Path = field(default_factory=_default_frontend_dist)
    audio_cache_dir: Path = field(default_factory=_default_audio_cache_dir)
    tts_voice: str = "KR"
    tts_speed: float = 1.0
