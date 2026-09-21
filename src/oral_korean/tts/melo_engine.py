"""MeloTTS adapter: the only module in the project that knows MeloTTS exists.

MeloTTS lives in the optional `tts` extra, so `melo` is imported inside the method rather
than at module level: a default install must be able to import this module, and the whole
test suite runs against a fake engine without MeloTTS present.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from oral_korean.tts.base import SpeechSynthesisError

LANGUAGE = "KR"
INSTALL_HINT = "MeloTTS is not installed. Run `uv sync --extra tts` to install it."

# Serialises every synthesis in the process, not merely those on one engine instance.
#
# FastAPI runs a sync `def` route in a threadpool, so two browser requests reach the one
# shared engine on two threads at once - which MeloTTS does not survive. Its Korean path
# loads a BERT model (`kykim/bert-kor-base`) through an unguarded lazy cache in
# `melo/text/japanese_bert.py`: `if model_id not in models: ... from_pretrained(...)`.
# Two threads both miss that check, and their `from_pretrained` calls then interleave
# inside the meta-device initialisation transformers loads through, leaving one thread
# holding a model whose weights were never materialised. The `.to(device)` that follows
# dies with "Cannot copy out of meta tensor; no data!", and the question never speaks.
# Measured in the container: 4 of 4 concurrent calls fail, 1 of 1 serial call succeeds.
#
# Module-level rather than per-instance because the state at risk is MeloTTS's own module
# globals and the transformers loader, both process-wide: two engine instances would race
# exactly as two threads on one instance do. Serialising costs nothing real here, since
# synthesis is CPU-bound torch inference that already spreads across every core.
_SYNTHESIS_LOCK = threading.Lock()


class MeloSpeechEngine:  # pylint: disable=too-few-public-methods
    """Speaks Korean with MeloTTS, loading the checkpoint once per instance."""

    def __init__(self) -> None:
        """Build the adapter without touching MeloTTS: loading is deferred to first use."""
        self._model: Any = None

    def synthesise(self, text: str, *, voice: str, speed: float, destination: Path) -> None:
        """Write `text` as a WAV at `destination`, spoken by `voice` at `speed`.

        Blocks until any synthesis already running in this process has finished, so a
        burst of requests is spoken one after another rather than failing: see
        `_SYNTHESIS_LOCK`.
        """
        with _SYNTHESIS_LOCK:
            model = self._load_model()
            speaker_ids = model.hps.data.spk2id
            if voice not in speaker_ids:
                raise SpeechSynthesisError(
                    f"Unknown voice {voice!r}. Available: {sorted(speaker_ids)}."
                )

            try:
                model.tts_to_file(
                    text,
                    speaker_ids[voice],
                    output_path=str(destination),
                    speed=speed,
                )
            # MeloTTS raises whatever torch, the G2P stack or the checkpoint raise; callers
            # of this seam only ever have to catch SpeechSynthesisError.
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise SpeechSynthesisError(f"MeloTTS failed to speak {text!r}: {exc}") from exc

    def _load_model(self) -> Any:
        """Return the loaded MeloTTS model, building it on first use.

        Loading reads a checkpoint from disk and takes seconds, so it happens once per
        engine instance rather than once per synthesis. Only ever called while
        `_SYNTHESIS_LOCK` is held, which is what makes the check-then-build below safe -
        without it two first calls would each see `None` and build their own model.
        """
        if self._model is not None:
            return self._model

        try:
            from melo.api import TTS  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            # MeloTTS imports every language it ships, so an ImportError here is just as
            # likely to be one of its own dependencies failing to load as a missing
            # install. Blaming the install in that case points the reader at the wrong
            # fix, so only a genuinely absent `melo` gets the install hint.
            missing = exc.name or "" if isinstance(exc, ModuleNotFoundError) else ""
            if missing.split(".", maxsplit=1)[0] == "melo":
                raise SpeechSynthesisError(INSTALL_HINT) from exc
            raise SpeechSynthesisError(
                f"MeloTTS is installed but could not be imported: {exc}"
            ) from exc

        try:
            self._model = TTS(language=LANGUAGE)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise SpeechSynthesisError(
                f"Could not load the MeloTTS {LANGUAGE} model: {exc}"
            ) from exc
        return self._model
