"""Application configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def _default_frontend_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for the FastAPI app and its dev server."""

    host: str = "127.0.0.1"
    port: int = 8000
    frontend_dist: Path = field(default_factory=_default_frontend_dist)
