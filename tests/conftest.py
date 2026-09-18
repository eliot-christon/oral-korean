"""Shared fixtures for the oral_korean test suite."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

# Content markers used to prove *which* file the app actually served, without
# the test re-implementing any HTML/JS parsing of its own.
INDEX_MARKER = "FAKE_FRONTEND_INDEX_MARKER"
ASSET_CONTENT = "console.log('FAKE_FRONTEND_ASSET_MARKER');"
ASSET_RELATIVE_PATH = "assets/index-abc123.js"

# Shape of the fake WAV written by `FakeSpeechEngine`. The rate is arbitrary and
# deliberately meaningless: nothing in the cache layer reads it, and no test asserts a
# sample rate anywhere (MeloTTS's Korean rate is unverified, see T02).
FAKE_WAV_SAMPLE_RATE = 16_000
FAKE_WAV_FRAMES = 1_024


@dataclass(frozen=True)
class FakeFrontendBuild:
    """A minimal fake `frontend/dist/` build for exercising static serving.

    Attributes:
        dist_dir: the fake build directory, suitable for `AppConfig(frontend_dist=...)`.
        index_marker: a string expected to appear in the served index page's body.
        asset_url_path: the URL path (starting with "/") at which the asset should be
            reachable once the app serves `dist_dir`.
        asset_content: the exact body expected when fetching `asset_url_path`.
    """

    dist_dir: Path
    index_marker: str
    asset_url_path: str
    asset_content: str


@pytest.fixture
def fake_frontend_build(tmp_path: Path) -> FakeFrontendBuild:
    """Create a fresh fake `dist/` directory with an `index.html` and one asset.

    A fresh directory is created per call (never a shared mutable fixture), so tests
    cannot leak state into one another via the filesystem.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text(
        f"<!doctype html><html><body>{INDEX_MARKER}</body></html>",
        encoding="utf-8",
    )

    asset_path = dist_dir / ASSET_RELATIVE_PATH
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text(ASSET_CONTENT, encoding="utf-8")

    return FakeFrontendBuild(
        dist_dir=dist_dir,
        index_marker=INDEX_MARKER,
        asset_url_path=f"/{ASSET_RELATIVE_PATH}",
        asset_content=ASSET_CONTENT,
    )


def write_fake_wav(path: Path, *, frames: int = FAKE_WAV_FRAMES) -> None:
    """Write a small but genuinely playable mono WAV at `path`, using only the stdlib.

    Used instead of arbitrary bytes so that a cache layer which one day sanity-checks
    the file it produced (a RIFF header, a readable duration) still sees a real WAV, and
    so the fake engine's output is honest about the contract "engine writes a WAV".
    """
    # `wave.Wave_write` rather than `wave.open(..., "wb")`: the latter's overloads defeat
    # pylint's inference, which then reports the writer's methods as missing.
    with wave.Wave_write(str(path)) as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(FAKE_WAV_SAMPLE_RATE)
        handle.writeframes(b"\x00\x01" * frames)


@dataclass(frozen=True)
class SynthesisCall:
    """One recorded call to `FakeSpeechEngine.synthesise`.

    Attributes:
        text: the text the cache layer asked to have spoken.
        voice: the voice name the cache layer resolved for this request.
        speed: the speech speed the cache layer resolved for this request.
        destination: the file the engine was told to write. The cache is expected to
            hand over a temporary path inside the cache directory, not the final one.
    """

    text: str
    voice: str
    speed: float
    destination: Path


FakeEngineBehaviour = Literal["writes_wav", "writes_empty_file", "writes_nothing"]


class FakeSpeechEngine:
    """An offline stand-in for a `SpeechEngine`, recording every call it receives.

    This is the reason the suite runs without MeloTTS, torch or model weights. It is
    injected into `AudioCache` as a plain constructor argument, so no patching is needed
    anywhere in the cache tests.

    A fresh instance must be built per test (never shared): `calls` is mutable state.
    """

    def __init__(
        self,
        *,
        behaviour: FakeEngineBehaviour = "writes_wav",
        error: Exception | None = None,
    ) -> None:
        """Configure what this engine does when asked to synthesise.

        Args:
            behaviour: "writes_wav" produces a real little WAV, "writes_empty_file"
                produces a zero-byte file (a truncated synthesis), "writes_nothing"
                returns successfully without creating the file at all.
            error: when set, the engine records the call and then raises this instead of
                writing anything.
        """
        self.behaviour = behaviour
        self.error = error
        self.calls: list[SynthesisCall] = []

    @property
    def call_count(self) -> int:
        """How many times `synthesise` has been called on this instance."""
        return len(self.calls)

    def synthesise(self, text: str, *, voice: str, speed: float, destination: Path) -> None:
        """Record the request, then behave as configured."""
        self.calls.append(
            SynthesisCall(text=text, voice=voice, speed=speed, destination=destination)
        )
        if self.error is not None:
            raise self.error
        if self.behaviour == "writes_wav":
            write_fake_wav(destination)
        elif self.behaviour == "writes_empty_file":
            destination.write_bytes(b"")
        # "writes_nothing": deliberately leaves `destination` absent.
