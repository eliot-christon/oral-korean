"""Tests for the speech-synthesis layer: the engine seam, and the on-disk audio cache.

Framing-mode note: none of the production code below exists yet. These tests are written
from T02's acceptance criteria and test contract, and they define the contract the
implementation must satisfy:

- `oral_korean.tts.base.SpeechSynthesisError(RuntimeError)` - the single error type for
  any synthesis failure, raised by both the engine and the cache.
- `oral_korean.tts.base.SpeechEngine` - a `typing.Protocol` with exactly one method,
  `synthesise(self, text: str, *, voice: str, speed: float, destination: Path) -> None`.
  The engine writes a WAV to `destination` and knows nothing about caching.
- `oral_korean.tts.cache.AudioCache(engine, *, cache_dir: Path, voice: str, speed: float)`
  with `get_or_synthesise(text, *, voice: str | None = None, speed: float | None = None)
  -> Path`. The engine is a plain constructor argument, so every cache test below injects
  `FakeSpeechEngine` and needs no patching at all.
- `oral_korean.tts.melo_engine.MeloSpeechEngine()` - constructible with no arguments,
  importing `melo` lazily (inside the method) so the module imports fine without the
  `tts` extra, and reusing one loaded model per instance.
- `oral_korean.config.AppConfig` gains `audio_cache_dir: Path`, `tts_voice: str` and
  `tts_speed: float`, all defaulted and all overridable by keyword.

Everything here runs offline: no torch, no model weights, no network, no audio playback.
The one test that needs the real engine is skip-marked. No test asserts a sample rate -
MeloTTS's Korean rate is unverified, so the skipped test reads it from the written file.
"""

from __future__ import annotations

import importlib
import inspect
import os
import re
import sys
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from conftest import FakeSpeechEngine, SynthesisCall

from oral_korean.config import AppConfig
from oral_korean.tts.base import SpeechEngine, SpeechSynthesisError
from oral_korean.tts.cache import AudioCache
from oral_korean.tts.melo_engine import MeloSpeechEngine

# Sample data: Sino-Korean numerals, the first thing this layer will ever speak.
TEXT = "사십이"  # 42
OTHER_TEXT = "사십삼"  # 43
VOICE = "KR"
OTHER_VOICE = "KR-ALT"
SPEED = 1.0
OTHER_SPEED = 0.7

# A cache filename must be built from a hash, so only these characters may appear in it.
SAFE_FILENAME = re.compile(r"[A-Za-z0-9._-]+")


def make_cache(
    engine: SpeechEngine,
    cache_dir: Path,
    *,
    voice: str = VOICE,
    speed: float = SPEED,
) -> AudioCache:
    """Build an `AudioCache` over `cache_dir`.

    The single place the constructor shape is spelled out, so a signature change costs
    one edit here rather than one per test.
    """
    return AudioCache(engine, cache_dir=cache_dir, voice=voice, speed=speed)


def cache_files(cache_dir: Path) -> list[Path]:
    """Every file currently in `cache_dir` (empty list when the directory is absent)."""
    if not cache_dir.exists():
        return []
    return sorted(path for path in cache_dir.iterdir() if path.is_file())


# ---------------------------------------------------------------------------------
# The seam itself
# ---------------------------------------------------------------------------------


def test_speech_synthesis_error_is_a_runtime_error() -> None:
    """One dedicated error type, usable as a `RuntimeError` by callers that do not care."""
    assert issubclass(SpeechSynthesisError, RuntimeError)
    assert "boom" in str(SpeechSynthesisError("boom"))


def test_fake_engine_satisfies_the_speech_engine_protocol() -> None:
    """The test double must be substitutable for a real engine.

    The real check is static: mypy runs in strict mode, so this assignment fails the
    build if `SpeechEngine.synthesise` and `FakeSpeechEngine.synthesise` disagree on
    argument names, keyword-only-ness or types.
    """
    engine: SpeechEngine = FakeSpeechEngine()

    assert callable(engine.synthesise)


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        (AudioCache.__init__, ["self", "engine"], ["cache_dir", "voice", "speed"]),
        (AudioCache.get_or_synthesise, ["self", "text"], ["voice", "speed"]),
        (SpeechEngine.synthesise, ["self", "text"], ["voice", "speed", "destination"]),
        (MeloSpeechEngine.synthesise, ["self", "text"], ["voice", "speed", "destination"]),
        (FakeSpeechEngine.synthesise, ["self", "text"], ["voice", "speed", "destination"]),
    ],
    ids=[
        "AudioCache.__init__",
        "AudioCache.get_or_synthesise",
        "SpeechEngine.synthesise",
        "MeloSpeechEngine.synthesise",
        "FakeSpeechEngine.synthesise",
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """Parameter names, order and keyword-only-ness are the contract, not an accident.

    Voice, speed and destination are keyword-only on purpose: `synthesise(text, "KR", 1.0,
    path)` reads as four interchangeable values and a transposed pair would be caught by
    nothing at runtime. Pinning the kinds here means a later "harmless" signature tidy-up
    that silently breaks every caller fails a test instead.
    """
    parameters = inspect.signature(function).parameters
    kinds = {name: parameter.kind for name, parameter in parameters.items()}

    assert [n for n, k in kinds.items() if k is inspect.Parameter.POSITIONAL_OR_KEYWORD] == (
        positional
    )
    assert [n for n, k in kinds.items() if k is inspect.Parameter.KEYWORD_ONLY] == keyword_only
    assert not [n for n, k in kinds.items() if k is inspect.Parameter.VAR_KEYWORD]


# ---------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------


def test_app_config_exposes_tts_defaults() -> None:
    """`AppConfig()` must keep working with no arguments and expose the three TTS fields.

    The cache directory is required to be absolute: a relative default would write audio
    wherever the process happened to be started, which is a silent, confusing bug.
    """
    config = AppConfig()

    assert isinstance(config.audio_cache_dir, Path)
    assert config.audio_cache_dir.is_absolute()
    assert isinstance(config.tts_voice, str)
    assert config.tts_voice != ""
    assert isinstance(config.tts_speed, float)
    assert config.tts_speed > 0


def test_app_config_accepts_tts_overrides(tmp_path: Path) -> None:
    """All three TTS fields are overridable by keyword, so tests can point at `tmp_path`."""
    config = AppConfig(audio_cache_dir=tmp_path / "audio", tts_voice="KR", tts_speed=0.8)

    assert config.audio_cache_dir == tmp_path / "audio"
    assert config.tts_voice == "KR"
    assert config.tts_speed == pytest.approx(0.8)


def test_audio_cache_can_be_built_from_app_config(tmp_path: Path) -> None:
    """The config fields must line up with the cache's constructor, types included."""
    config = AppConfig(audio_cache_dir=tmp_path / "audio", tts_voice="KR", tts_speed=0.8)
    engine = FakeSpeechEngine()
    cache = AudioCache(
        engine,
        cache_dir=config.audio_cache_dir,
        voice=config.tts_voice,
        speed=config.tts_speed,
    )

    path = cache.get_or_synthesise(TEXT)

    assert path.parent.resolve() == config.audio_cache_dir.resolve()
    assert engine.calls[0].voice == "KR"
    assert engine.calls[0].speed == pytest.approx(0.8)


# ---------------------------------------------------------------------------------
# Cache behaviour: hits, misses and identity
# ---------------------------------------------------------------------------------


def test_first_request_synthesises_a_non_empty_wav(tmp_path: Path) -> None:
    """A cache miss calls the engine exactly once and yields a real file on disk."""
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio")

    path = cache.get_or_synthesise(TEXT)

    assert path.exists()
    assert path.stat().st_size > 0
    assert engine.call_count == 1


def test_cache_directory_is_created_on_demand(tmp_path: Path) -> None:
    """A first run has no cache directory yet; that must not be an error."""
    cache_dir = tmp_path / "does-not-exist-yet" / "audio"
    assert not cache_dir.exists()
    cache = make_cache(FakeSpeechEngine(), cache_dir)

    path = cache.get_or_synthesise(TEXT)

    assert cache_dir.is_dir()
    assert path.parent.resolve() == cache_dir.resolve()


def test_engine_receives_the_requested_text_voice_and_speed(tmp_path: Path) -> None:
    """The cache resolves its defaults and passes them through unchanged."""
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio", voice=VOICE, speed=SPEED)

    cache.get_or_synthesise(TEXT)

    call: SynthesisCall = engine.calls[0]
    assert call.text == TEXT
    assert call.voice == VOICE
    assert call.speed == pytest.approx(SPEED)


def test_second_identical_request_is_served_from_the_cache(tmp_path: Path) -> None:
    """The same text, voice and speed must reuse the file instead of re-synthesising."""
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio")

    first = cache.get_or_synthesise(TEXT)
    second = cache.get_or_synthesise(TEXT)

    assert second == first
    assert engine.call_count == 1


def test_a_new_cache_instance_reuses_files_from_a_previous_run(tmp_path: Path) -> None:
    """The filename must be a stable hash, not a per-process one.

    Python's builtin `hash()` is salted per interpreter run, so a cache keyed on it would
    silently re-synthesise everything after a restart while the old files pile up. A
    second `AudioCache` over the same directory stands in for that restart.
    """
    cache_dir = tmp_path / "audio"
    first_path = make_cache(FakeSpeechEngine(), cache_dir).get_or_synthesise(TEXT)

    second_engine = FakeSpeechEngine()
    second_path = make_cache(second_engine, cache_dir).get_or_synthesise(TEXT)

    assert second_path == first_path
    assert second_engine.call_count == 0
    assert len(cache_files(cache_dir)) == 1


def test_different_text_produces_different_paths(tmp_path: Path) -> None:
    """Two numbers must not collide onto one file."""
    cache = make_cache(FakeSpeechEngine(), tmp_path / "audio")

    forty_two = cache.get_or_synthesise(TEXT)
    forty_three = cache.get_or_synthesise(OTHER_TEXT)

    assert forty_two != forty_three
    assert forty_two.exists()
    assert forty_three.exists()


def test_different_voice_produces_different_paths(tmp_path: Path) -> None:
    """The voice is part of the cache identity, at call level as well as default level."""
    cache = make_cache(FakeSpeechEngine(), tmp_path / "audio", voice=VOICE)

    default_voice = cache.get_or_synthesise(TEXT)
    other_voice = cache.get_or_synthesise(TEXT, voice=OTHER_VOICE)

    assert default_voice != other_voice
    assert default_voice.exists()
    assert other_voice.exists()


def test_different_speed_produces_different_paths(tmp_path: Path) -> None:
    """The speed is part of the cache identity: 0.7x of a number is not 1.0x of it."""
    cache = make_cache(FakeSpeechEngine(), tmp_path / "audio", speed=SPEED)

    default_speed = cache.get_or_synthesise(TEXT)
    slow = cache.get_or_synthesise(TEXT, speed=OTHER_SPEED)

    assert default_speed != slow
    assert default_speed.exists()
    assert slow.exists()


def test_explicit_arguments_matching_the_defaults_hit_the_same_entry(tmp_path: Path) -> None:
    """`None` means "use the default", it must not become a cache key of its own."""
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio", voice=VOICE, speed=SPEED)

    implicit = cache.get_or_synthesise(TEXT)
    explicit = cache.get_or_synthesise(TEXT, voice=VOICE, speed=SPEED)

    assert explicit == implicit
    assert engine.call_count == 1


def test_an_integer_speed_is_the_same_entry_as_the_equal_float(tmp_path: Path) -> None:
    """`speed=1` and `speed=1.0` are the same speech, so they must be the same file.

    `speed: float` accepts an `int` under Python's numeric tower, and both mypy and every
    caller will eventually pass one. Keying on the unnormalised value would double the
    cache and re-synthesise identical audio, silently and for ever.
    """
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio", speed=SPEED)

    from_float = cache.get_or_synthesise(TEXT, speed=1.0)
    from_int = cache.get_or_synthesise(TEXT, speed=1)

    assert from_int == from_float
    assert engine.call_count == 1


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("사십이", VOICE), ("사십", f"이{VOICE}")),
        (("ab", "cd"), ("abc", "d")),
    ],
    ids=["korean-text-into-voice", "ascii-boundary-shift"],
)
def test_shifting_the_boundary_between_text_and_voice_does_not_collide(
    left: tuple[str, str], right: tuple[str, str], tmp_path: Path
) -> None:
    """Two requests whose fields concatenate to the same string must not share a file.

    This is the only observable consequence of hashing each field length-prefixed rather
    than joined: without it, text "사십" spoken by voice "이KR" and text "사십이" spoken by
    "KR" hash identically, and one of the two is served the other's audio. A collision
    here is silent - the user simply hears the wrong thing.
    """
    cache = make_cache(FakeSpeechEngine(), tmp_path / "audio")

    left_path = cache.get_or_synthesise(left[0], voice=left[1])
    right_path = cache.get_or_synthesise(right[0], voice=right[1])

    assert left_path != right_path
    assert left_path.exists()
    assert right_path.exists()


def test_text_reaches_the_engine_exactly_as_given(tmp_path: Path) -> None:
    """Surrounding whitespace is not stripped: what was asked for is what is spoken.

    Blankness is checked on the stripped text, but the request itself is never rewritten -
    the cache does not get to decide that "  사십이\\n" should be pronounced differently
    from what the caller passed. The documented cost is that the padded form is a separate
    cache entry holding identical audio; deduplicating it would mean normalising text,
    which is a decision for whoever owns the exercise layer, not for the cache.
    """
    padded = f"  {TEXT}\n"
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio")

    plain_path = cache.get_or_synthesise(TEXT)
    padded_path = cache.get_or_synthesise(padded)

    assert engine.calls[1].text == padded
    assert padded_path != plain_path


def test_cached_file_is_a_wav_inside_the_cache_directory(tmp_path: Path) -> None:
    """The returned path is a `.wav` in the cache directory, ready to be served as-is."""
    cache_dir = tmp_path / "audio"
    cache = make_cache(FakeSpeechEngine(), cache_dir)

    path = cache.get_or_synthesise(TEXT)

    assert path.suffix == ".wav"
    assert path.parent.resolve() == cache_dir.resolve()


@pytest.mark.parametrize(
    "text",
    [
        "사십이 는/뭐?",
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "nul",
        "a" * 500,
    ],
    ids=[
        "spaces-slash-question",
        "posix-traversal",
        "windows-traversal",
        "windows-device-name",
        "very-long",
    ],
)
def test_text_never_leaks_into_the_filename(text: str, tmp_path: Path) -> None:
    """The filename is a hash of the request, never the caller's text.

    This is the path-traversal guard: whatever the text contains, the file must land
    inside the cache directory under a name free of separators and metacharacters. The
    Hangul cases are covered by the same rule, since a hashed name is plain ASCII. The
    over-long case guards the filesystem's name-length limit, and "nul" guards against a
    reserved Windows device name ever becoming a real filename.
    """
    cache_dir = tmp_path / "audio"
    cache = make_cache(FakeSpeechEngine(), cache_dir)

    path = cache.get_or_synthesise(text)

    assert path.parent.resolve() == cache_dir.resolve()
    assert path.exists()
    assert len(path.name) <= 128
    assert SAFE_FILENAME.fullmatch(path.name) is not None
    assert ".." not in path.name


# ---------------------------------------------------------------------------------
# Atomic writes and failure handling
# ---------------------------------------------------------------------------------


def test_engine_writes_to_a_temporary_file_inside_the_cache_directory(tmp_path: Path) -> None:
    """Synthesis goes to a temporary file that is then renamed into place.

    The temporary file must live in the cache directory itself, so the rename stays on
    one filesystem and is therefore atomic, and nothing must survive the call but the
    final WAV.
    """
    cache_dir = tmp_path / "audio"
    engine = FakeSpeechEngine()
    cache = make_cache(engine, cache_dir)

    path = cache.get_or_synthesise(TEXT)

    temporary = engine.calls[0].destination
    assert temporary != path
    assert temporary.parent.resolve() == cache_dir.resolve()
    assert not temporary.exists()
    assert cache_files(cache_dir) == [path]


@pytest.mark.parametrize(
    "text",
    ["", "   ", "\t\n", "　"],
    ids=["empty", "spaces", "control-whitespace", "ideographic-space"],
)
def test_blank_text_is_rejected(text: str, tmp_path: Path) -> None:
    """Nothing to speak is an error, not a zero-byte WAV the browser will choke on."""
    cache_dir = tmp_path / "audio"
    engine = FakeSpeechEngine()
    cache = make_cache(engine, cache_dir)

    with pytest.raises(SpeechSynthesisError):
        cache.get_or_synthesise(text)

    assert engine.call_count == 0
    assert cache_files(cache_dir) == []


@pytest.mark.parametrize(
    "raised",
    [RuntimeError("engine exploded"), SpeechSynthesisError("engine exploded")],
    ids=["generic-error", "synthesis-error"],
)
def test_engine_failure_surfaces_and_leaves_no_file(raised: Exception, tmp_path: Path) -> None:
    """A failing engine yields this module's error type, naming the text, and cleans up.

    Both cases are wrapped, including the one where the engine already raised a
    `SpeechSynthesisError`: the contract is that the message names the text that failed,
    which the engine's own message cannot guarantee.
    """
    cache_dir = tmp_path / "audio"
    cache = make_cache(FakeSpeechEngine(error=raised), cache_dir)

    with pytest.raises(SpeechSynthesisError) as excinfo:
        cache.get_or_synthesise(TEXT)

    assert TEXT in str(excinfo.value)
    assert cache_files(cache_dir) == []


def test_engine_failure_keeps_the_original_error_as_its_cause(tmp_path: Path) -> None:
    """`raise ... from exc`: losing the engine's own error makes failures undebuggable."""
    original = RuntimeError("torch is sulking")
    cache = make_cache(FakeSpeechEngine(error=original), tmp_path / "audio")

    with pytest.raises(SpeechSynthesisError) as excinfo:
        cache.get_or_synthesise(TEXT)

    assert excinfo.value.__cause__ is original


def test_engine_that_writes_nothing_is_an_error(tmp_path: Path) -> None:
    """A silent engine (returns without producing the file) must not look like success."""
    cache_dir = tmp_path / "audio"
    cache = make_cache(FakeSpeechEngine(behaviour="writes_nothing"), cache_dir)

    with pytest.raises(SpeechSynthesisError):
        cache.get_or_synthesise(TEXT)

    assert cache_files(cache_dir) == []


def test_engine_that_writes_an_empty_file_is_an_error(tmp_path: Path) -> None:
    """A zero-byte result is a failed synthesis, and must never be renamed into place."""
    cache_dir = tmp_path / "audio"
    cache = make_cache(FakeSpeechEngine(behaviour="writes_empty_file"), cache_dir)

    with pytest.raises(SpeechSynthesisError):
        cache.get_or_synthesise(TEXT)

    assert cache_files(cache_dir) == []


def test_a_zero_byte_cached_file_is_resynthesised(tmp_path: Path) -> None:
    """A truncated file left by an older crash must not be served for ever after."""
    engine = FakeSpeechEngine()
    cache = make_cache(engine, tmp_path / "audio")
    path = cache.get_or_synthesise(TEXT)
    path.write_bytes(b"")  # simulate the truncated leftover of an interrupted run

    again = cache.get_or_synthesise(TEXT)

    assert again == path
    assert again.stat().st_size > 0
    assert engine.call_count == 2


def test_resynthesis_replaces_the_stale_file_rather_than_failing_or_appending(
    tmp_path: Path,
) -> None:
    """Renaming onto an existing path must overwrite it, on every platform.

    `os.rename` raises `FileExistsError` on Windows when the destination exists, so this
    pins the choice of `os.replace`: the re-synthesis path always renames onto something.
    Reading the result back as a WAV proves the bytes were replaced wholesale, not
    appended to the leftover.
    """
    cache_dir = tmp_path / "audio"
    cache = make_cache(FakeSpeechEngine(), cache_dir)
    path = cache.get_or_synthesise(TEXT)
    path.write_bytes(b"")

    again = cache.get_or_synthesise(TEXT)

    with wave.open(str(again), "rb") as handle:
        assert handle.getnframes() > 0
    assert cache_files(cache_dir) == [again]


def test_a_leftover_temporary_file_is_ignored_by_a_later_run(tmp_path: Path) -> None:
    """A crash mid-synthesis leaves a `.tmp`; the next run must work around it, not on it.

    The leftover survives, and that is deliberate: cleaning the cache directory is out of
    T02's scope. What matters is that it is never mistaken for a finished WAV, so the new
    synthesis gets its own temporary name and its own final path.
    """
    cache_dir = tmp_path / "audio"
    cache_dir.mkdir(parents=True)
    stale = cache_dir / "interrupted.wav.tmp"
    stale.write_bytes(b"RIFF-truncated")
    engine = FakeSpeechEngine()
    cache = make_cache(engine, cache_dir)

    path = cache.get_or_synthesise(TEXT)

    assert path != stale
    assert path.suffix == ".wav"
    assert path.stat().st_size > 0
    assert engine.call_count == 1
    assert stale.exists()


def fail_the_rename(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Make the cache's rename-into-place step fail.

    monkeypatch is the last resort here and it is warranted: a full disk, or a reader
    holding the destination open (a real prospect on Windows, where this project's cache
    lives inside a OneDrive folder), cannot be produced from a test. Patching `os.replace`
    in the cache module's namespace is the narrowest seam available - the engine has
    already succeeded and written its temporary file by the time it fires.
    """

    def exploding_replace(src: object, dst: object) -> None:
        raise error

    monkeypatch.setattr(os, "replace", exploding_replace)


def test_a_failed_rename_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the rename fails, the temporary file must not survive as cache litter."""
    cache_dir = tmp_path / "audio"
    engine = FakeSpeechEngine()
    cache = make_cache(engine, cache_dir)
    fail_the_rename(monkeypatch, OSError("no space left on device"))

    # Either error type satisfies this test: it is about the cleanup, not the wrapping.
    with pytest.raises((OSError, SpeechSynthesisError)):
        cache.get_or_synthesise(TEXT)

    assert engine.call_count == 1
    assert cache_files(cache_dir) == []


def test_a_failed_rename_surfaces_as_a_synthesis_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`get_or_synthesise` promises one error type; a failed rename is no exception.

    Its docstring reads "Raises: SpeechSynthesisError: the text was blank, or synthesis
    failed", and from a caller's seat a WAV that never made it into place is a synthesis
    that failed. Leaking a raw `OSError` past the seam means the route handler that calls
    this has to catch two unrelated error families to stay honest.
    """
    cache = make_cache(FakeSpeechEngine(), tmp_path / "audio")
    fail_the_rename(monkeypatch, OSError("no space left on device"))

    with pytest.raises(SpeechSynthesisError):
        cache.get_or_synthesise(TEXT)


# ---------------------------------------------------------------------------------
# The MeloTTS adapter, exercised without MeloTTS
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MeloCall:
    """One recorded `tts_to_file` call on the fake MeloTTS model."""

    text: str
    speaker_id: object
    output_path: Path
    speed: float


@dataclass
class MeloRecorder:
    """What the fake `melo.api` module saw: model constructions and synthesis calls."""

    constructions: list[tuple[tuple[object, ...], dict[str, object]]] = field(
        default_factory=list
    )
    calls: list[MeloCall] = field(default_factory=list)


def install_fake_melo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    speakers: dict[str, int] | None = None,
    fails_with: Exception | None = None,
    load_fails_with: Exception | None = None,
    during_call: Callable[[], None] | None = None,
) -> MeloRecorder:
    """Put a fake `melo.api` in `sys.modules` and return a recorder of what it receives.

    monkeypatch is unavoidable here: simulating the presence (or absence) of an
    uninstalled third-party module is exactly a `sys.modules` question. The fake pins the
    MeloTTS API the adapter is expected to call: `melo.api.TTS(...)`, then
    `model.tts_to_file(text, speaker_id, output_path, speed=...)`, with speaker ids read
    from `model.hps.data.spk2id`. It accepts `output_path` and `speed` positionally or by
    keyword, so the adapter is free to call it either way.

    `fails_with` makes synthesis raise; `load_fails_with` makes the model construction
    itself raise, which is what a missing or corrupt checkpoint looks like. `during_call`
    runs inside `tts_to_file`, while the adapter believes MeloTTS is busy, which is the
    only window in which overlapping threads can be observed.
    """
    recorder = MeloRecorder()
    speaker_ids = {VOICE: 0} if speakers is None else speakers

    class FakeTTS:  # pylint: disable=too-few-public-methods
        """Stand-in for `melo.api.TTS`."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            recorder.constructions.append((args, kwargs))
            if load_fails_with is not None:
                raise load_fails_with
            self.hps = SimpleNamespace(data=SimpleNamespace(spk2id=dict(speaker_ids)))

        def tts_to_file(
            self,
            text: str,
            speaker_id: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            """Record the call and write where MeloTTS would have written."""
            if during_call is not None:
                during_call()
            raw_output = kwargs.get("output_path", args[0] if args else None)
            raw_speed = kwargs.get("speed", args[4] if len(args) > 4 else 1.0)
            destination = Path(str(raw_output))
            recorder.calls.append(
                MeloCall(
                    text=text,
                    speaker_id=speaker_id,
                    output_path=destination,
                    speed=float(raw_speed) if isinstance(raw_speed, int | float) else 1.0,
                )
            )
            if fails_with is not None:
                raise fails_with
            destination.write_bytes(b"RIFF....WAVEfake-audio-bytes")

    melo_package = ModuleType("melo")
    melo_api = ModuleType("melo.api")
    # Written through `vars()` rather than `setattr`: mypy checks literal `setattr` calls
    # on a module object and would reject an attribute the real `melo` does not declare.
    vars(melo_api)["TTS"] = FakeTTS
    vars(melo_package)["api"] = melo_api
    monkeypatch.setitem(sys.modules, "melo", melo_package)
    monkeypatch.setitem(sys.modules, "melo.api", melo_api)
    return recorder


def poison_melo_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any `import melo` raise, whether or not the `tts` extra is installed.

    `None` in `sys.modules` makes the import machinery raise `ImportError` (not
    `ModuleNotFoundError`), which is deliberate: the adapter must catch `ImportError` so
    that a half-broken install is explained just as clearly as a missing one.
    """
    monkeypatch.setitem(sys.modules, "melo", None)
    monkeypatch.setitem(sys.modules, "melo.api", None)


def test_importing_the_tts_package_does_not_import_melo(monkeypatch: pytest.MonkeyPatch) -> None:
    """`import oral_korean.tts` must work on a default install, with no extra."""
    poison_melo_import(monkeypatch)

    module = importlib.reload(importlib.import_module("oral_korean.tts"))

    assert module is not None


def test_importing_the_melo_engine_module_does_not_import_melo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `melo` import is lazy: reloading the adapter with `melo` broken must not raise."""
    poison_melo_import(monkeypatch)

    module = importlib.reload(importlib.import_module("oral_korean.tts.melo_engine"))

    assert hasattr(module, "MeloSpeechEngine")


def test_constructing_the_engine_without_the_extra_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building the adapter must be free; only synthesising needs MeloTTS present."""
    poison_melo_import(monkeypatch)

    engine = MeloSpeechEngine()

    assert engine is not None


def test_missing_melo_install_names_the_sync_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing install is explained with the command that fixes it, not a traceback."""
    poison_melo_import(monkeypatch)
    engine = MeloSpeechEngine()

    with pytest.raises(SpeechSynthesisError) as excinfo:
        engine.synthesise(TEXT, voice=VOICE, speed=SPEED, destination=tmp_path / "out.wav")

    assert "uv sync --extra tts" in str(excinfo.value)


def test_melo_engine_loads_the_korean_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The model is built for Korean, and the literal is asserted, not the constant.

    Comparing against `melo_engine.LANGUAGE` would pass just as happily if that constant
    were changed to "EN": the trainer would then speak fluent English at a Korean learner
    and no test would notice. How the language reaches `TTS(...)` is left free - only the
    value is the contract.
    """
    recorder = install_fake_melo(monkeypatch)
    engine = MeloSpeechEngine()

    engine.synthesise(TEXT, voice=VOICE, speed=SPEED, destination=tmp_path / "out.wav")

    args, kwargs = recorder.constructions[0]
    assert "KR" in (*args, *kwargs.values())


def test_melo_engine_explains_a_checkpoint_that_will_not_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A present-but-broken install fails like everything else on this seam.

    An interrupted weight download is far more likely than a clean absence, and it raises
    from `TTS(...)`, not from the import. The original error is kept as the cause: "could
    not load the model" alone is undebuggable.
    """
    original = OSError("checkpoint.pth is truncated")
    install_fake_melo(monkeypatch, load_fails_with=original)
    engine = MeloSpeechEngine()

    with pytest.raises(SpeechSynthesisError) as excinfo:
        engine.synthesise(TEXT, voice=VOICE, speed=SPEED, destination=tmp_path / "out.wav")

    assert "KR" in str(excinfo.value)
    assert excinfo.value.__cause__ is original


def test_melo_model_is_built_once_per_engine_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Loading the checkpoint takes seconds: it happens once per instance, not per call."""
    recorder = install_fake_melo(monkeypatch)
    engine = MeloSpeechEngine()

    engine.synthesise(TEXT, voice=VOICE, speed=SPEED, destination=tmp_path / "one.wav")
    engine.synthesise(OTHER_TEXT, voice=VOICE, speed=SPEED, destination=tmp_path / "two.wav")

    assert len(recorder.constructions) == 1
    assert len(recorder.calls) == 2


class OverlapProbe:  # pylint: disable=too-few-public-methods
    """Counts how many threads are inside the fake MeloTTS model at the same time.

    `peak` is the whole assertion: 1 means the adapter serialised the calls, anything
    above it means two threads were inside MeloTTS at once.
    """

    def __init__(self, hold: float = 0.05) -> None:
        self._lock = threading.Lock()
        self._hold = hold
        self._active = 0
        self.peak = 0

    def __call__(self) -> None:
        with self._lock:
            self._active += 1
            self.peak = max(self.peak, self._active)
        # Long enough that genuinely parallel callers are caught overlapping; a serialised
        # run just pays it once per call.
        time.sleep(self._hold)
        with self._lock:
            self._active -= 1


def synthesise_from_threads(engine: MeloSpeechEngine, tmp_path: Path, count: int) -> list[str]:
    """Start `count` synthesises at once and return what they raised, empty if nothing did."""
    failures: list[str] = []

    def work(index: int) -> None:
        try:
            engine.synthesise(
                f"{TEXT}{index}",
                voice=VOICE,
                speed=SPEED,
                destination=tmp_path / f"{index}.wav",
            )
        # The point is to report whatever a racing thread raised, not to predict it.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failures.append(repr(exc))

    threads = [threading.Thread(target=work, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return failures


def test_concurrent_synthesis_is_serialised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One thread inside MeloTTS at a time, because two is what breaks it.

    The regression test for the failure the trainer actually hit: clicking through
    questions faster than they synthesise put several requests in FastAPI's threadpool at
    once, MeloTTS's unguarded lazy BERT load raced, and each one came back to the browser
    as "Could not synthesise audio for this question". Serialising is asserted through the
    engine's own seam rather than by reaching for the lock, so the guarantee survives a
    change of mechanism.
    """
    probe = OverlapProbe()
    recorder = install_fake_melo(monkeypatch, during_call=probe)
    engine = MeloSpeechEngine()

    failures = synthesise_from_threads(engine, tmp_path, count=4)

    assert not failures
    assert probe.peak == 1
    # Serialised, not dropped: every caller still gets its audio.
    assert len(recorder.calls) == 4
    assert len(recorder.constructions) == 1


def test_melo_engine_forwards_text_speed_and_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The adapter passes the request through to MeloTTS and writes where it was told."""
    recorder = install_fake_melo(monkeypatch, speakers={VOICE: 0})
    destination = tmp_path / "out.wav"
    engine = MeloSpeechEngine()

    engine.synthesise(TEXT, voice=VOICE, speed=OTHER_SPEED, destination=destination)

    call = recorder.calls[0]
    assert call.text == TEXT
    assert call.speaker_id == 0
    assert call.output_path == destination
    assert call.speed == pytest.approx(OTHER_SPEED)
    assert destination.exists()


def test_melo_engine_rejects_an_unknown_voice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unknown speaker is a synthesis error, never a raw `KeyError` from MeloTTS."""
    install_fake_melo(monkeypatch, speakers={VOICE: 0})
    engine = MeloSpeechEngine()

    with pytest.raises(SpeechSynthesisError) as excinfo:
        engine.synthesise(
            TEXT, voice="NO-SUCH-VOICE", speed=SPEED, destination=tmp_path / "out.wav"
        )

    assert "NO-SUCH-VOICE" in str(excinfo.value)


def test_melo_engine_wraps_a_failing_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Whatever MeloTTS throws, callers only ever have to catch `SpeechSynthesisError`."""
    install_fake_melo(monkeypatch, fails_with=ValueError("g2p failed"))
    engine = MeloSpeechEngine()

    with pytest.raises(SpeechSynthesisError):
        engine.synthesise(TEXT, voice=VOICE, speed=SPEED, destination=tmp_path / "out.wav")


# ---------------------------------------------------------------------------------
# The real engine, skipped by default
# ---------------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("ORAL_KOREAN_TTS_E2E"),
    reason=(
        "needs the tts extra, the MeloTTS weights and a network; set ORAL_KOREAN_TTS_E2E=1"
        " to run it, which the Linux container can do: see the Dockerfile for why Windows"
        " cannot"
    ),
)
def test_real_melotts_synthesis_writes_a_playable_wav(tmp_path: Path) -> None:
    """End to end against the real MeloTTS: audible length, then a genuine cache hit.

    The sample rate is read from the file rather than compared to a constant: MeloTTS's
    Korean rate is not verified by this project and must not be pinned anywhere.
    """
    cache_dir = tmp_path / "audio"
    cache = AudioCache(MeloSpeechEngine(), cache_dir=cache_dir, voice=VOICE, speed=SPEED)

    path = cache.get_or_synthesise("안녕하세요")

    assert path.exists()
    assert path.stat().st_size > 0
    with wave.open(str(path), "rb") as handle:
        duration_seconds = handle.getnframes() / float(handle.getframerate())
    assert duration_seconds > 0.2

    first_mtime = path.stat().st_mtime_ns
    again = cache.get_or_synthesise("안녕하세요")

    assert again == path
    assert again.stat().st_mtime_ns == first_mtime
