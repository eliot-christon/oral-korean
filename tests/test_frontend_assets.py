"""Cross-language check T05's own test contract asks for: vitest can prove the frontend
behaves given a stubbed backend, but only something on the Python side can prove the
paths the frontend actually calls are paths the real FastAPI app registers.

`frontend/src/api.ts` now exists and is what both tests below check against:

- `test_every_frontend_api_literal_matches_a_registered_route` guards against a typo'd
  path in `api.ts` (or anywhere else under `frontend/src/`): every `/api/...` literal
  found there must have a matching entry in `harness.app.openapi()["paths"]`.
- `test_the_required_numbers_paths_are_referenced_somewhere_in_the_frontend` guards the
  other direction: `api.ts` must actually reference the systems catalogue, create-question
  and answer paths (three of T04's four numbers-exercise paths - see below for why not
  four), not just avoid referencing anything wrong.

**Literal-collection judgment call, worth trusting only as far as stated**: this is a
regex over `.ts`/`.tsx` source text, not a real TypeScript parser (a hand-rolled JS/TS
parser is out of scope for a Python test, and `ast` only parses Python). It finds a
string/template literal that starts with `/api/` right after its opening quote, and
normalises a `${...}` interpolation to the same placeholder FastAPI's own `{question_id}`
path params are normalised to. It will miss:
  - a path built by concatenation (`'/api/exercises/numbers/questions/' + id + '/audio'`)
    instead of one template literal - the `/api/exercises/numbers/questions/` half would
    still be found, but without the trailing `/audio`, so it would not match any real
    route and would wrongly fail the first test above.
  - a path built from a shared prefix constant (`` `${BASE}/systems` ``) - the literal
    text does not start with `/api/` at all in that case, so it is invisible to this
    regex entirely (a false negative for the second test).
  - a `/api/...`-looking string inside a comment or an unrelated string (say, an error
    message), which would wrongly count as a real reference for the first test.
Kept anyway, per the ticket's own "best-effort" framing, rather than quietly downgrading
it to a smoke test - but whoever writes `api.ts` should keep each endpoint's path as one
self-contained literal (template interpolation only for path params, no shared `/api`
prefix constant spread across a `${...}`) specifically so this check keeps working. If
that turns out impractical, the sturdier alternative is cross-checking the frontend's
*built* JS bundle (`frontend/dist/assets/*.js`) instead of TypeScript source - heavier,
and not attempted here since it would need a real build to exist, which framing mode
cannot assume. The backend side of the comparison already reads `harness.app.openapi()`
rather than walking `app.routes` directly - see `backend_route_paths` for why.

**Why the audio path is excluded from the "must be referenced" list**: per T05's own
ground truth, `CreateQuestionResponse.audio_url` already arrives as a full, ready-to-use
relative URL - the frontend is expected to hand it straight to an `<audio src=...>`
without ever reconstructing `/api/exercises/numbers/questions/{id}/audio` itself. So,
unlike the systems/create-question/answer paths, no literal for it should ever appear in
`frontend/src/` even in a correct implementation; requiring one would pin a wrong
contract. `test_every_frontend_api_literal_matches_a_registered_route` still covers it
indirectly: if some future change *did* start constructing that URL by hand, and got it
wrong, it would show up there as an unmatched literal.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import NumbersHarness

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
FRONTEND_ROOT = FRONTEND_SRC.parent

PARAM_MARKER = "<param>"

# A bare "http://" or "https://": T02's fonts and stylesheet must be self-hosted npm
# packages bundled by Vite, never loaded from a CDN such as Google Fonts at runtime.
_EXTERNAL_URL_PATTERN = re.compile(r"https?://")

# A quoted or backticked string starting with "/api/", up to the next quote/backtick.
_API_LITERAL_PATTERN = re.compile(r"""['"`](/api/[^'"`]*)['"`]""")
_TEMPLATE_PARAM_PATTERN = re.compile(r"\$\{[^}]*\}")
_FASTAPI_PARAM_PATTERN = re.compile(r"\{[^}]+\}")

# The systems catalogue, create-question and answer paths must be literally referenced
# somewhere under `frontend/src/` once T05 is done. The audio path is deliberately not
# in this list - see the module docstring for why.
REQUIRED_NUMBERS_PATHS = (
    "/api/exercises/numbers/systems",
    "/api/exercises/numbers/questions",
    f"/api/exercises/numbers/questions/{PARAM_MARKER}/answer",
)


def _normalise_template_params(path: str) -> str:
    """Replace every `${...}` interpolation with the same marker FastAPI's own
    `{question_id}`-style path params are normalised to, so a frontend literal and a
    backend route path are directly comparable strings."""
    return _TEMPLATE_PARAM_PATTERN.sub(PARAM_MARKER, path)


def frontend_api_literals() -> set[str]:
    """Every `/api/...` string/template literal found under `frontend/src/`.

    Test files are excluded on purpose: `App.test.tsx` itself contains several
    `/api/exercises/numbers/...` literals (as stub URLs), and counting those would make
    `test_the_required_numbers_paths_are_referenced_somewhere_in_the_frontend` pass even
    if the real `api.ts`/`App.tsx` never referenced them at all.
    """
    literals: set[str] = set()
    for pattern in ("*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(pattern):
            if ".test." in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            for match in _API_LITERAL_PATTERN.finditer(text):
                literals.add(_normalise_template_params(match.group(1)))
    return literals


def test_the_required_numbers_paths_are_referenced_somewhere_in_the_frontend() -> None:
    """`frontend/src/` must actually call the systems catalogue, create-question and
    answer routes (the audio path is excluded - see module docstring)."""
    frontend_literals = frontend_api_literals()

    missing = [path for path in REQUIRED_NUMBERS_PATHS if path not in frontend_literals]

    assert not missing, f"frontend/src/ does not yet reference: {missing}"


def backend_route_paths(harness: NumbersHarness) -> set[str]:
    """Every API path FastAPI has registered on `harness.app`, with `{param}`-style path
    segments normalised the same way as the frontend literals above.

    Reads `app.openapi()["paths"]` rather than walking `app.routes` directly: the
    installed FastAPI/Starlette version keeps included routers as lazily-matched,
    nested objects (an `_IncludedRouter` wrapping the original `APIRouter`, with no
    flat `.path` per entry), so `app.routes` no longer exposes a simple per-route
    `path` attribute for a mounted sub-router. `openapi()` is what FastAPI itself
    already resolves the effective route tree into, so it stays correct across that
    kind of internal restructuring - and it conveniently excludes `/docs`, `/redoc`
    and `/openapi.json`, none of which the frontend should ever reference anyway.
    """
    paths: set[str] = set(harness.app.openapi()["paths"].keys())
    return {_FASTAPI_PARAM_PATTERN.sub(PARAM_MARKER, path) for path in paths}


def test_every_frontend_api_literal_matches_a_registered_route(
    numbers_harness: NumbersHarness,
) -> None:
    """Nothing under `frontend/src/` (test files aside) references an `/api/...` path
    the backend does not actually serve. Everything the numbers exercise's routes are
    mounted under already carries the `/api` prefix `create_app` establishes (see
    `src/oral_korean/api/app.py`), so comparing full paths on both sides, with no prefix
    stripped on either, is the right comparison.
    """
    frontend_literals = frontend_api_literals()
    backend_paths = backend_route_paths(numbers_harness)

    unmatched = {literal for literal in frontend_literals if literal not in backend_paths}

    assert not unmatched, (
        f"frontend/src/ references API path(s) the backend does not register: {unmatched}"
    )


def _html_files_directly_under_frontend_root() -> list[Path]:
    """The `.html` files the dev server can serve: `frontend/index.html` today, and
    `frontend/preview.html` once T02
    (`.claude/work/ui-redesign/tickets/T02-design-foundation.md`) creates it. Non-recursive
    on purpose: `frontend/dist/` (a build artefact, once one exists) and
    `frontend/node_modules/` must never be scanned."""
    return sorted(FRONTEND_ROOT.glob("*.html"))


def _css_files_under_frontend_src() -> list[Path]:
    """Every `.css` file anywhere under `frontend/src/`: today `index.css` and
    `styles.css`, and any file T02's font imports or `@theme` tokens add."""
    return sorted(FRONTEND_SRC.rglob("*.css"))


def test_stylesheets_and_fonts_are_self_hosted() -> None:
    """T02: no `.html` file directly under `frontend/` and no `.css` file under
    `frontend/src/` loads a stylesheet or a font from another host. The chosen font
    package(s) ship as npm dependencies and are bundled by Vite specifically so nothing
    here depends on a CDN such as Google Fonts at runtime (the later deployment epic's own
    reason - see `epic.md`, "A Korean-friendly font ... self-hosted from an npm package
    rather than loaded from a CDN at runtime"). Adding
    `@import url("https://fonts.googleapis.com/css2?family=Jua");` to `index.css`, or a
    `<link rel="stylesheet" href="https://...">` to `preview.html`, must fail this test.

    Scanned, as of this test: `frontend/index.html`, `frontend/preview.html` (once T02
    creates it), and every `.css` file under `frontend/src/` (today `index.css` and
    `styles.css`).
    """
    scanned = _html_files_directly_under_frontend_root() + _css_files_under_frontend_src()

    offenders: dict[str, str] = {}
    for path in scanned:
        match = _EXTERNAL_URL_PATTERN.search(path.read_text(encoding="utf-8"))
        if match is not None:
            offenders[str(path.relative_to(FRONTEND_ROOT))] = match.group(0)

    assert not offenders, f"external stylesheet/font reference(s) found: {offenders}"
