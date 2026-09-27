"""Shared fixtures for the oral_korean test suite."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import wave
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from oral_korean.api.app import create_app
from oral_korean.config import AppConfig
from oral_korean.srs.memory import Familiarity, MemoryState, seed


@pytest.fixture(autouse=True)
def _isolate_the_default_database_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point `AppConfig`'s default database path at a per-test file (vocab-core T04).

    Autouse and unconditional, so no test - present or future, whether or not it ever
    builds a `WordStore` - can reach the real `<repo>/.data/oral-korean.sqlite3` merely by
    constructing a default `AppConfig()`. `monkeypatch.setenv` rather than a fixture
    parameter: `AppConfig`'s own default has to read this from the environment, the same
    way `ORAL_KOREAN_HOST` already works, so patching the environment is the only seam
    that reaches it without every call site threading a path through.
    """
    monkeypatch.setenv("ORAL_KOREAN_DATABASE_PATH", str(tmp_path / "oral-korean.sqlite3"))


HARNESS_START: Final = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
"""Where every harness clock starts: the instant the vocabulary tests call T0."""


class FakeClock:
    """A clock a test moves by hand, injected as `create_app`'s `clock`.

    A fresh instance per app (never shared): `now` is mutable state.
    """

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by `delta`."""
        self.now += delta


@dataclass
class NumbersHarness:
    """A `create_app` instance wired to a `FakeSpeechEngine`, a `FakeClock` and a database.

    Named after the numbers exercise, its first user, and kept under that name so the numbers
    tests stay untouched; the vocabulary route tests (vocab-core T05) use the same one, which
    is why this lives in `conftest.py`. Numbers-exercise T05's asset test reuses it too.

    Attributes:
        app: the `FastAPI` instance itself, so a test can reach into `app.state` for the
            pending-question store instead of the HTTP API - needed to read back the drawn
            number and Korean text that the create-question response must never leak.
        client: a `TestClient` bound to `app`.
        engine: the `FakeSpeechEngine` injected into `app`, so a test can inspect
            `engine.calls` to check what was (or was not) synthesised, and how many times.
        config: the `AppConfig` the app was built from; its `database_path` is this
            instance's own file under `base_dir`, not yet created.
        clock: the `FakeClock` injected into `app`, starting at `HARNESS_START`.
    """

    app: FastAPI
    client: TestClient
    engine: FakeSpeechEngine
    config: AppConfig
    clock: FakeClock


def build_numbers_harness(
    base_dir: Path, *, engine: FakeSpeechEngine | None = None
) -> NumbersHarness:
    """Build one isolated `NumbersHarness` rooted at `base_dir`.

    A plain function as well as a fixture, so a test that needs two independent app
    instances (the pending-question-store and database isolation contracts) can call it
    twice with two different directories instead of juggling two fixtures for one test.

    Args:
        base_dir: root directory for this instance's frontend, audio cache and database.
        engine: the `FakeSpeechEngine` to inject; `None` builds a fresh default one. A
            test that needs to observe a synthesis failure passes its own
            `FakeSpeechEngine(error=...)` or `FakeSpeechEngine(behaviour="writes_nothing")`
            here instead of reaching into the harness after the fact.
    """
    engine = engine if engine is not None else FakeSpeechEngine()
    clock = FakeClock(HARNESS_START)
    config = AppConfig(
        frontend_dist=base_dir / "dist",
        audio_cache_dir=base_dir / "audio",
        database_path=base_dir / "data" / "vocabulary.sqlite3",
    )
    app = create_app(config, speech_engine=engine, clock=clock)
    return NumbersHarness(
        app=app, client=TestClient(app), engine=engine, config=config, clock=clock
    )


@pytest.fixture
def numbers_harness(tmp_path: Path) -> NumbersHarness:
    """One isolated app + client + fake engine, freshly built per test."""
    return build_numbers_harness(tmp_path)


def leaks(body: object, question_id: str, needle: str) -> bool:
    """Whether `needle` appears anywhere in `body` once the opaque id is redacted.

    The id is expected to appear in the response (as `question_id` and inside
    `audio_url`), and an opaque id built from arbitrary hex digits will, essentially
    always, coincidentally contain any single digit somewhere in its length - that
    coincidence says nothing about the answer leaking. Redacting the id first is what
    keeps this check about real disclosure instead of about the shape of a UUID.

    `ensure_ascii=False`, because `json.dumps` otherwise writes every Hangul syllable as a
    `\\uXXXX` escape, and a Korean needle could then never be found, leak or no leak.
    Shared by the numbers and the vocabulary sessions suites (vocab-sessions T03).
    """
    redacted = json.dumps(body, ensure_ascii=False).replace(question_id, "")
    return needle in redacted


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


FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "oral_korean.tts",
    "oral_korean.api",
    "oral_korean.storage",
    "fastapi",
    "httpx",
    "melo",
    "requests",
    "sqlite3",
)
"""What a pure module may never reach for, directly or transitively by name.

One list rather than one per package: a name added to a copy and not to the others would
leave that layer silently unguarded, which is the opposite of what `test_layering.py` is
for. `korean/`, `srs/` and `exercises/` decide what to say, how well a word is known and
whether an answer is right, and nothing there may talk to the outside world: not the
network, not HTTP, and not a database. `sqlite3` and `oral_korean.storage` belong to the
storage layer alone (vocab-core T04); a pure module that reached for either could no
longer be tested without a file on disk. Each package adds its own stricter entries in
that file: `korean/` and `srs/` forbid the rest of the project, and `exercises/` forbids
everything but `korean/` and `srs/` (opened by vocab-core T03, the ticket that gave a word
its familiarity level and memory state, both `srs/` values). `storage/` itself is allowed
`sqlite3` (it is the one place SQL lives) but forbidden everything else here, including
`oral_korean.storage`'s own siblings `api/` and `tts/`: see `STORAGE_PACKAGE` in
`test_layering.py`, which starts from this list and removes `sqlite3` and
`oral_korean.storage` itself before adding the rest of the project back in.
"""


def imported_names_in_source(source: str, package: str) -> set[str]:
    """Every name `source` imports, spelled as an absolute dotted name.

    Every spelling of an import has to land on the same names, or a prefix check has a hole
    in it: `from oral_korean import tts` reads as `oral_korean.tts`, and a relative
    `from ..tts import cache` is resolved against `package` (the package the source lives
    in) first. What is imported *from* a module is recorded next to the module itself,
    which is what makes the first case visible at all.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = "." * node.level + (node.module or "")
            base = importlib.util.resolve_name(target, package) if node.level else target
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def imported_module_names(module: ModuleType) -> set[str]:
    """Every name `module` imports, read from its source rather than from runtime.

    Reading the source statically is the point: an import that only happens inside a
    function (a deliberately lazy one, or a sneaked-in dependency) shows up just the same,
    and nothing has to be executed or patched to find it. Used by `test_layering.py`, which
    keeps every module in `korean/` and `exercises/` inside its layer.
    """
    source_path = inspect.getsourcefile(module)
    assert source_path is not None, f"{module.__name__} has no source file on disk"

    return imported_names_in_source(
        Path(source_path).read_text(encoding="utf-8"), module.__package__ or ""
    )


def signature_shape(function: Callable[..., object]) -> tuple[list[str], list[str]]:
    """Return `function`'s parameter names, split into positional then keyword-only.

    Parameter names and order are part of the contract a module publishes, not an
    accident of its first draft, so several modules pin them. Lives here rather than in
    one test file because the check is identical wherever it is made.
    """
    kinds = {
        name: parameter.kind
        for name, parameter in inspect.signature(function).parameters.items()
    }
    return (
        [name for name, kind in kinds.items() if kind is inspect.Parameter.POSITIONAL_OR_KEYWORD],
        [name for name, kind in kinds.items() if kind is inspect.Parameter.KEYWORD_ONLY],
    )


# ---------------------------------------------------------------------------------
# Vocabulary sessions over HTTP (vocab-sessions T03)
# ---------------------------------------------------------------------------------
# Shared by `test_api_vocab_sessions.py` (starting, questions, audio, lifetime) and
# `test_api_vocab_answers.py` (answering and scoring), split only for pylint's module
# length. The route shapes these helpers rely on are documented in the first file.

type Json = dict[str, Any]
"""A JSON object as a route returns it."""

VOCAB: Final = "/api/vocab"
WORDS: Final = f"{VOCAB}/words"
SESSIONS: Final = f"{VOCAB}/sessions"

H2T: Final = "hangul_to_translation"
T2H: Final = "translation_to_hangul"
V2H: Final = "voice_to_hangul"
V2T: Final = "voice_to_translation"
ALL_DIRECTIONS: Final = (H2T, T2H, V2H, V2T)
VOICE_DIRECTIONS: Final = (V2H, V2T)
HANGUL_ANSWERED: Final = (T2H, V2H)
"""The directions answered with the Korean; the other two are answered with a translation."""

KOREAN: Final = "사과"
TRANSLATIONS: Final = ["apple", "pomme"]
"""The target word every single-word test asks about, added as `apple; pomme`."""

DISTRACTORS: Final = (("배", "pear"), ("감", "persimmon"), ("포도", "grape"))
"""Added `very_well`: neither new nor due at T0, so they only ever appear as options."""

DONT_KNOW: Final[Mapping[str, object]] = {"dont_know": True}
MAX_ITEMS: Final = 50


def next_path(session_id: str) -> str:
    return f"{SESSIONS}/{session_id}/next"


def audio_path(item_id: str) -> str:
    return f"{VOCAB}/items/{item_id}/audio"


def answer_path(item_id: str) -> str:
    return f"{VOCAB}/items/{item_id}/answer"


def instant(text: str) -> datetime:
    """A datetime from the JSON, aware as the API writes it."""
    return datetime.fromisoformat(text)


def add_word(
    client: TestClient,
    korean: str,
    translations: str,
    *,
    tags: list[str] | None = None,
    familiarity: str = "new",
) -> Json:
    """Add a word through the word route; it must be accepted."""
    body = {
        "korean": korean,
        "translations": translations,
        "tags": tags or [],
        "familiarity": familiarity,
    }
    response = client.post(WORDS, json=body)
    assert response.status_code == 201, response.text
    word: Json = response.json()
    return word


def add_target(client: TestClient, familiarity: str = "new") -> int:
    """Add the target word; its id."""
    word = add_word(client, KOREAN, "; ".join(TRANSLATIONS), familiarity=familiarity)
    word_id: int = word["id"]
    return word_id


def add_distractors(client: TestClient) -> None:
    for korean, translation in DISTRACTORS:
        add_word(client, korean, translation, familiarity="very_well")


def seeded_well() -> MemoryState:
    """What the word routes seed for `well` at T0, fuzzing off: a two-day first delay, which
    FSRS never fuzzes, so the route's own seed is the same."""
    result = seed(Familiarity.WELL, HARNESS_START, fuzzing=False)
    assert result is not None
    return result[0]


def move_to_well_due_date(harness: NumbersHarness) -> None:
    harness.clock.advance(seeded_well().next_review - HARNESS_START)


def start_session(client: TestClient, kind: str, **fields: object) -> Response:
    response: Response = client.post(SESSIONS, json={"kind": kind, **fields})
    return response


def started(client: TestClient, kind: str, **fields: object) -> str:
    """Start a session that must be accepted; its id."""
    response = start_session(client, kind, **fields)
    assert response.status_code == 201, response.text
    session_id: str = response.json()["session_id"]
    return session_id


def next_item(client: TestClient, session_id: str) -> Json:
    response = client.post(next_path(session_id))
    assert response.status_code == 200, response.text
    item: Json = response.json()
    return item


def answer(client: TestClient, item_id: str, body: Mapping[str, object]) -> Response:
    response: Response = client.post(answer_path(item_id), json=dict(body))
    return response


def answered(client: TestClient, item_id: str, body: Mapping[str, object]) -> Json:
    response = answer(client, item_id, body)
    assert response.status_code == 200, response.text
    verdict: Json = response.json()
    return verdict


def word_detail(client: TestClient, word_id: int) -> Json:
    response = client.get(f"{WORDS}/{word_id}")
    assert response.status_code == 200, response.text
    body: Json = response.json()
    return body


def pending_items(harness: NumbersHarness) -> int:
    """How many items the app holds pending: only the size of the store is read."""
    return len(harness.app.state.vocab_items)


def sessions_held(harness: NumbersHarness) -> int:
    return len(harness.app.state.vocab_sessions)


def option_index(question: Json, text: str) -> int:
    """The index of the one option containing `text`: an option found by its word."""
    matches = [index for index, option in enumerate(question["options"]) if text in option]
    assert len(matches) == 1, question["options"]
    return matches[0]


def correct_option(question: Json) -> str:
    """The target word's own option: its Korean, or the option naming its translations."""
    text = KOREAN if question["direction"] in HANGUL_ANSWERED else TRANSLATIONS[0]
    option: str = question["options"][option_index(question, text)]
    return option


def right_choice(question: Json) -> Mapping[str, object]:
    return {"choice": question["options"].index(correct_option(question))}


def wrong_choice(question: Json) -> Mapping[str, object]:
    right = question["options"].index(correct_option(question))
    return {"choice": next(i for i in range(len(question["options"])) if i != right)}


def right_typed(direction: str) -> Mapping[str, object]:
    return {"answer": KOREAN if direction in HANGUL_ANSWERED else TRANSLATIONS[0]}


@dataclass(frozen=True)
class Asked:
    """A session holding one pending question about the target word."""

    session_id: str
    word_id: int
    question: Json

    @property
    def item_id(self) -> str:
        item_id: str = self.question["item_id"]
        return item_id


def ask_by_choice(harness: NumbersHarness, direction: str) -> Asked:
    """A learn session over the new target, past its presentation: asked by choice."""
    word_id = add_target(harness.client)
    add_distractors(harness.client)
    session_id = started(harness.client, "learn", directions=[direction])
    assert next_item(harness.client, session_id)["type"] == "presentation"
    question = next_item(harness.client, session_id)
    assert question["type"] == "question"
    assert question["mode"] == "choice"
    return Asked(session_id, word_id, question)


def ask_by_typing(harness: NumbersHarness, direction: str) -> Asked:
    """A review session over the target seeded `well`, at its due date: asked by typing."""
    word_id = add_target(harness.client, familiarity="well")
    move_to_well_due_date(harness)
    session_id = started(harness.client, "review", directions=[direction])
    question = next_item(harness.client, session_id)
    assert question["type"] == "question"
    assert question["mode"] == "typing"
    return Asked(session_id, word_id, question)


def ask(harness: NumbersHarness, direction: str, mode: str) -> Asked:
    if mode == "choice":
        return ask_by_choice(harness, direction)
    return ask_by_typing(harness, direction)


def walk(client: TestClient, session_id: str, body: Mapping[str, object]) -> list[Json]:
    """Every item up to and including the end, answering each question with `body`."""
    items: list[Json] = []
    while len(items) < MAX_ITEMS and (not items or items[-1]["type"] != "end"):
        item = next_item(client, session_id)
        items.append(item)
        if item["type"] == "question":
            answered(client, item["item_id"], body)
    assert items[-1]["type"] == "end", f"the session did not end within {MAX_ITEMS} items"
    return items
