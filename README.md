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

## Status

Early development - currently just a project scaffold.