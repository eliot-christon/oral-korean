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

**A vocabulary trainer** for your own words: you add them, then learn and review them in
short sessions, heard as well as read.

Speech is [MeloTTS](https://github.com/myshell-ai/MeloTTS) (MIT), run locally with the
Korean checkpoint. Generated audio is cached on disk, so a number or a word heard twice is
synthesised once.

## The vocabulary trainer

### Adding words

Under **Words**, add one word at a time (the Korean, then its translations, several
separated by `;`), or paste a whole list, one word per line:

```
사과 ; apple
집 ; house; home
가다	to go
```

On each line the first `;` or a tab separates the Korean from its translations; any further
`;` separates several translations. Tags (`food, topik 1`) apply to every word added
together and let you filter the list and your sessions.

Each word gets a **familiarity level**, which decides where it starts:

- **New**: not known yet. It waits for a learn session.
- **A little**, **Well**, **Very well**: known already. The word counts as reviewed once,
  graded Hard, Good or Easy, and starts with a score (14%, 20% or 38%) and a first review in
  about 1, 2 or 8 days.

### Score and recall

Each word's memory is modelled with [FSRS](https://github.com/open-spaced-repetition/py-fsrs),
the scheduler behind modern spaced-repetition apps.

- **Score** is the word's strength, read off FSRS's stability (how many days until you are
  likely to forget it). It goes **up on a right answer and down on a miss**, and nothing else
  moves it. 100% means a year of stability.
- **Recall** is the predicted chance you would get the word right now. It reads 100% for a
  day after any review, even a missed one, then decays until the word is due again.

### Sessions

- **Learn** introduces new words, oldest first: each is shown (Korean, translations, audio),
  then asked straight away.
- **Review** asks the words that are due, most overdue first.

You can limit a session to one tag and choose how many words it takes (5 to learn and 20 to
review by default).

Every question comes in one of four **directions**: Hangul to translation, translation to
Hangul, voice to Hangul (you hear it, you write the Korean) and voice to translation. Untick
the two voice directions to practise without audio.

A weak word is asked by **multiple choice**; once it is stronger (two days of stability), you
**type** the answer, which counts for more. Typed translations ignore case, accents,
punctuation and extra spaces, and any of the word's translations is accepted; typed Korean
ignores spacing and punctuation. "I don't know" is always there and counts as a miss.

Only your **first answer** to each word counts. A missed word comes back at the end of the
session for practice, at most twice, and a practice answer is **not scored**. After every
answer you see the word, and for a scored one how its score and next review moved.

### Your data

Your words, tags and history live in one SQLite file, `.data/oral-korean.sqlite3`, outside
git. The container and `uv run main.py` share it, so your vocabulary is the same in both run
modes, but **never run both at once**.

- **Back it up** by copying the file while the backend is stopped.
- **Start from scratch** by stopping the backend and deleting the file.
- `ORAL_KOREAN_DATABASE_PATH` points the backend at another file.

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
checkpoint; after that each new number or word is around a second, and repeats are instant.

**After pulling changes**, rebuild the image and re-sync the host: `fsrs`, which the
vocabulary trainer needs, is a Python dependency.

```bash
docker compose up --build backend
uv sync
```

To try it on a phone, start the UI with `npm run dev -- --host` and open the address it
prints for your network on the phone.

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

While `npm run dev` runs, http://localhost:5173/preview.html shows the design system
(colours, type, every UI component in every state) with no backend needed.

`uv run pre-commit install` wires the Python checks into `git commit`. Note that
pre-commit covers **Python only**: a green commit says nothing about whether the frontend
builds. CI runs both sides on every push and pull request.

### Layout

```
main.py                  dev launcher
src/oral_korean/
  api/                   HTTP layer: FastAPI app, routes, helpers exercises share
  exercises/             exercise logic: numbers, vocabulary words and sessions
  korean/                language primitives shared between exercises
  srs/                   word memory with FSRS: seeds, grades, score, statistics
  storage/               the vocabulary in SQLite, with numbered migrations
  tts/                   speech synthesis behind a one-method interface
frontend/                Vite + React + TypeScript + Tailwind CSS
tests/                   pytest suite
```

The directories mark the seams between concerns. There is deliberately no plugin registry
or exercise base class: the second exercise showed two helpers worth sharing (pending
questions by opaque id, and synthesis with a text-free error), and nothing more.

## Status

Early but working. The number exercise and the vocabulary trainer are complete; dates and
time come next.
