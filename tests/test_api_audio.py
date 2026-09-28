"""Tests for `api/audio.py`: synthesise-or-502 shared by every exercise route.

`vocab-sessions` T01 extracts the numbers route's private `_synthesise_or_502` into a
helper that takes the text to speak directly, rather than a `NumberQuestion` - vocab needs
it for presentations and voice questions of its own, which are not `NumberQuestion`s. This
file is the contract that helper is written against, and it predates the implementation:

- `synthesise_or_502(cache: AudioCache, text: str) -> str` - returns the cached WAV path
  for `text` (via `cache.get_or_synthesise`), or, on a `SpeechSynthesisError`, logs the
  real error server-side and raises `fastapi.HTTPException(status_code=502, detail=...)`
  with the fixed, text-free detail `"Could not synthesise audio for this question."` -
  the exact string from the ticket's acceptance criteria, asserted verbatim below rather
  than imported, since the ticket does not say whether it stays a private module constant.

Takes an already-built `AudioCache` rather than a `Request`, so every test below builds one
directly from `FakeSpeechEngine` and `tmp_path` - no `FastAPI` app, no route, no
`create_app` - matching the ticket's "the audio cache accessor on `request.app.state`" as a
separate, thinner concern than this function (and one already covered indirectly by
`test_api_numbers.py`, unmodified by this ticket).

`FakeSpeechEngine` and `SpeechSynthesisError` are the same fakes `test_api_numbers.py`
uses for the equivalent numbers-route behaviour (offline, no MeloTTS, no network), so a
regression here and in the numbers suite would share one root cause instead of two.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from conftest import FakeSpeechEngine
from fastapi import HTTPException

from oral_korean.api.audio import synthesise_or_502
from oral_korean.tts.base import SpeechSynthesisError
from oral_korean.tts.cache import AudioCache

VOICE = "KR"
SPEED = 1.0
TEXT = "사과"
SYNTHESIS_FAILURE_DETAIL = "Could not synthesise audio for this question."

FAILING_ENGINES = pytest.mark.parametrize(
    "engine",
    [
        FakeSpeechEngine(error=SpeechSynthesisError("boom")),
        FakeSpeechEngine(behaviour="writes_nothing"),
    ],
    ids=["engine_raises", "engine_writes_no_audio"],
)


def build_cache(tmp_path: Path, engine: FakeSpeechEngine) -> AudioCache:
    """An `AudioCache` rooted at `tmp_path`, wired to `engine`; no app involved."""
    return AudioCache(engine, cache_dir=tmp_path, voice=VOICE, speed=SPEED)


def test_working_engine_returns_a_non_empty_wav_inside_the_cache_directory(
    tmp_path: Path,
) -> None:
    """A successful synthesis returns a real, playable-looking file under the cache dir."""
    cache = build_cache(tmp_path, FakeSpeechEngine())

    audio_path = synthesise_or_502(cache, TEXT)

    path = Path(audio_path)
    assert path.is_file()
    assert path.stat().st_size > 0
    assert path.parent == tmp_path


def test_second_call_for_the_same_text_does_not_call_the_engine_again(
    tmp_path: Path,
) -> None:
    """A cache hit on the second call means the engine is never invoked twice."""
    engine = FakeSpeechEngine()
    cache = build_cache(tmp_path, engine)

    first = synthesise_or_502(cache, TEXT)
    second = synthesise_or_502(cache, TEXT)

    assert first == second
    assert engine.call_count == 1


@FAILING_ENGINES
def test_failing_engine_raises_502_with_exactly_the_fixed_text_free_detail(
    engine: FakeSpeechEngine, tmp_path: Path
) -> None:
    """Whether the engine raises or silently writes nothing, the 502 detail is identical
    and names none of the text, the voice or the cache directory - only the real
    `SpeechSynthesisError` (built from the text it failed to speak) may say those, and it
    must never reach the response.
    """
    cache = build_cache(tmp_path, engine)

    with pytest.raises(HTTPException) as exc_info:
        synthesise_or_502(cache, TEXT)

    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail == SYNTHESIS_FAILURE_DETAIL
    assert TEXT not in detail
    assert VOICE not in detail
    assert str(tmp_path) not in detail


@FAILING_ENGINES
def test_the_real_error_is_logged_with_the_failing_text(
    engine: FakeSpeechEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The text-free 502 is a client-facing choice only: the server log still names the
    text that failed, which is where a developer needs it and a browser must never see it.
    """
    cache = build_cache(tmp_path, engine)

    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException):
        synthesise_or_502(cache, TEXT)

    assert any(TEXT in record.getMessage() for record in caplog.records)
