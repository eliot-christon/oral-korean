"""Synthesise-or-502, shared by every exercise route that speaks Korean text.

`SpeechSynthesisError` messages are built from the text they failed to speak (see
`tts/cache.py`), so relaying one to the client would hand over the very answer an exercise
exists to test. The real message is logged server-side; the response names nothing.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from oral_korean.tts.base import SpeechSynthesisError
from oral_korean.tts.cache import AudioCache

logger = logging.getLogger(__name__)

_SYNTHESIS_FAILURE_DETAIL = "Could not synthesise audio for this question."


def synthesise_or_502(cache: AudioCache, text: str) -> str:
    """Return the cached WAV path for `text`, or raise a 502 that names no Korean text."""
    try:
        audio_path = cache.get_or_synthesise(text)
    except SpeechSynthesisError as exc:
        logger.error("Speech synthesis failed: %s", exc)
        raise HTTPException(status_code=502, detail=_SYNTHESIS_FAILURE_DETAIL) from exc
    return str(audio_path)
