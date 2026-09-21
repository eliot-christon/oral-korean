# oral-korean

A Korean listening-comprehension trainer.

The goal is a set of small exercises that play or read out Korean audio and check whether
you understood it. More exercise types are planned over time (dates, time, basic
phrases, ...).

## What it does today

**Number recognition**, end to end: the app draws a number, speaks it in Korean, and you
type what you heard. It tells you whether you were right.

Both Korean numeral systems are supported, and you choose which one you are practising:

- **Sino-Korean** (영, 일, 이, 삼 ...) over **0 to 100** - prices, dates, phone numbers.
- **Native Korean** (하나, 둘, 셋 ...) over **1 to 99** - counting, ages, hours. It has no
  zero and conventionally no word past 99, so the range really does stop there.

You answer in digits either way. The answer is checked on the server: the browser is sent
an opaque question id and an audio URL, never the number and never its Korean text.

Speech is [MeloTTS](https://github.com/myshell-ai/MeloTTS) (MIT), run locally with the
Korean checkpoint. Generated audio is cached on disk, so a number heard twice is
synthesised once.

## Running it

You need [uv](https://docs.astral.sh/uv/), [Docker](https://docs.docker.com/) and
[node](https://nodejs.org/) 24.

**The backend runs in a container, and that is not optional.** MeloTTS's Korean
pronunciation stack cannot be installed on Windows at all: it needs a Korean MeCab that
collides with the Japanese one MeloTTS also loads, and the Windows-only alternative has
not shipped a usable wheel since Python 3.6. On a Windows host the backend starts and then
fails on the first question. Linux inside a container has neither problem.

```bash
# terminal 1: the API, with working Korean speech, on http://127.0.0.1:8000
docker compose up backend

# terminal 2: the UI on http://localhost:5173, proxying /api to the backend
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. The first question takes a few seconds while MeloTTS loads its
checkpoint; after that each new number is around a second, and repeats are instant.

### Without the container

One process serves both the API and the built frontend:

```bash
uv sync
cd frontend && npm ci && npm run build
uv run main.py            # http://127.0.0.1:8000
```

This is the closest thing to a deployment, and it is the right mode for checking the
production build. On Linux, add the speech engine with `uv sync --extra tts` and it works
fully. **On Windows this mode has no audio** for the reason above: the page loads and the
first question comes back as an error.

## Development

```bash
uv sync                              # Python dependencies, including dev tools
uv run ruff check .                  # lint
uv run mypy .                        # type check (strict)
uv run pylint $(git ls-files '*.py') # static analysis
uv run pytest                        # tests

cd frontend
npm run typecheck                    # tsc
npm run lint                         # oxlint
npm test                             # vitest
npm run build                        # production build
```

`uv run pre-commit install` wires the Python checks into `git commit`. Note that
pre-commit covers **Python only**: a green commit says nothing about whether the frontend
builds. CI runs both sides on every push and pull request.

### Layout

```
main.py                  dev launcher
src/oral_korean/
  api/                   HTTP layer: FastAPI app and routes
  exercises/             one module per exercise type
  korean/                language primitives shared between exercises
  tts/                   speech synthesis behind a one-method interface
frontend/                Vite + React + TypeScript
tests/                   pytest suite
```

The directories mark the seams between concerns. There is deliberately no plugin registry
or exercise base class yet: the second exercise type is what will show the shape worth
sharing.

## Status

Early but working. The number exercise is complete; the next exercise type has not been
started.
