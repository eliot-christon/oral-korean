"""The speech-engine seam: one protocol, one error type.

Exercises and the cache layer depend on this module, never on a concrete engine, so
swapping the engine is a one-file change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SpeechSynthesisError(RuntimeError):
    """Speech could not be synthesised.

    The single error type callers have to catch, whatever the engine failed at: a missing
    install, an unknown voice, a model that threw, or output that never appeared.
    """


class SpeechEngine(Protocol):  # pylint: disable=too-few-public-methods
    """Anything that can turn text into a WAV file on disk.

    One method is the whole point: the seam stays cheap to implement and cheap to fake.
    """

    def synthesise(self, text: str, *, voice: str, speed: float, destination: Path) -> None:
        """Write `text`, spoken by `voice` at `speed`, as a WAV at `destination`.

        Implementations raise `SpeechSynthesisError` on any failure, and know nothing
        about caching: `destination` is wherever the caller wants the audio.
        """
