"""Content-addressed WAV cache: synthesise once, reuse for ever after."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from oral_korean.tts.base import SpeechEngine, SpeechSynthesisError


def _digest(text: str, voice: str, speed: float) -> str:
    """Hash the whole request, so the filename can never be derived from the text itself.

    Each part is length-prefixed before hashing: plain concatenation would let a text
    ending in a voice name collide with a different text/voice pair.
    """
    digest = hashlib.sha256()
    for part in (text, voice, repr(float(speed))):
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


class AudioCache:  # pylint: disable=too-few-public-methods
    """Hands out WAV paths for spoken text, calling the engine only on a miss."""

    def __init__(
        self,
        engine: SpeechEngine,
        *,
        cache_dir: Path,
        voice: str,
        speed: float,
    ) -> None:
        """Cache the output of `engine` under `cache_dir`, defaulting to `voice`/`speed`."""
        self._engine = engine
        self._cache_dir = cache_dir
        self._voice = voice
        self._speed = speed

    def get_or_synthesise(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        """Return the WAV for `text`, synthesising it first if it is not already cached.

        Args:
            text: what to speak. Blank text is rejected rather than synthesised.
            voice: overrides the default voice; `None` means the default.
            speed: overrides the default speed; `None` means the default.

        Raises:
            SpeechSynthesisError: the text was blank, or synthesis failed. Nothing is
                left behind in the cache directory in either case.
        """
        if not text.strip():
            raise SpeechSynthesisError("Cannot synthesise blank text.")

        resolved_voice = self._voice if voice is None else voice
        resolved_speed = self._speed if speed is None else speed
        destination = self._cache_dir / f"{_digest(text, resolved_voice, resolved_speed)}.wav"

        # A zero-byte file is the leftover of an interrupted run, not a cache hit.
        if destination.exists() and destination.stat().st_size > 0:
            return destination

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._synthesise_into_place(text, resolved_voice, resolved_speed, destination)
        return destination

    def _synthesise_into_place(
        self, text: str, voice: str, speed: float, destination: Path
    ) -> None:
        """Synthesise to a temporary file next to `destination`, then rename it in.

        The temporary file shares the cache directory so the rename stays on one
        filesystem and is therefore atomic: a crash mid-synthesis can leave a stray
        temporary file, never a truncated WAV that later looks like a cache hit.

        Its suffix is `.wav` and not something like `.wav.tmp` because engines routinely
        infer the output format from the extension: MeloTTS hands the path to soundfile,
        which refuses an unknown one outright ("No format specified and unable to get
        format from file extension"). A leftover is still never served, since a lookup
        only ever builds the one digest-named path it wants.
        """
        handle, raw_path = tempfile.mkstemp(dir=self._cache_dir, suffix=".wav")
        os.close(handle)
        temporary = Path(raw_path)
        try:
            try:
                self._engine.synthesise(text, voice=voice, speed=speed, destination=temporary)
            # Engine errors are re-wrapped even when they are already a
            # SpeechSynthesisError: only this layer knows which text failed.
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise SpeechSynthesisError(f"Could not synthesise {text!r}: {exc}") from exc

            if not temporary.exists() or temporary.stat().st_size == 0:
                raise SpeechSynthesisError(
                    f"Engine produced no audio for {text!r} (voice {voice!r}, speed {speed})."
                )
            try:
                os.replace(temporary, destination)
            except OSError as exc:
                raise SpeechSynthesisError(
                    f"Could not store the audio for {text!r} at {destination}: {exc}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)
