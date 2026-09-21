"""Health-check route."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def get_health() -> dict[str, str]:
    """Report that the API is up."""
    return {"status": "ok"}
