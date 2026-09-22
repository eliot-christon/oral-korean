"""Hangul as people type it: a clean form to show, and a key that says "the same word".

The same Korean word reaches the backend in more than one shape. Input methods, on phones
and macOS especially, can send **decomposed** jamo (NFD: 사 as ᄉ + ᅡ) instead of the
precomposed syllable, and the two look identical while comparing unequal. Spacing (띄어쓰기)
is inconsistent even among native speakers, and a trailing `.` or `?` is common. Every
exercise that accepts typed Hangul, and the vocabulary's duplicate check, asks this module
rather than growing its own rule, so a word judged the same in one place is judged the same
everywhere.

The rule is deliberately narrow, because it decides whether a typed answer is right: too
strict marks right answers wrong, too lenient teaches a wrong spelling as right. Spacing,
punctuation, decomposition and the case of Latin letters (TV) never make a different word.
Anything else does, one vowel off included, since that is exactly the skill being tested.
There is no romanisation and no typo tolerance.

**NFC only, never NFKC.** NFC composes decomposed jamo back into syllables. It leaves
*compatibility* jamo (ㅅㅏㄱㅘ, the U+3131 block, what a keyboard shows on its keys) alone,
and so does this module: a string of them is not the word. NFKC would compose ㅅㅏㄱㅘ
into 사과, but it cannot give a syllable its final consonant (가ㄱ becomes 가ᄀ, not 각), so
it would accept some jamo spellings and refuse others at random.

Symbols (`~`, `+`), invisible format characters (a zero-width space) and the invisible
Hangul fillers (U+3164 and its kin, letters by category) are neither whitespace nor
punctuation, so they stay in the key. No ticket has decided otherwise yet.
"""

from __future__ import annotations

import unicodedata
from typing import Final

_FIRST_SYLLABLE: Final = "가"
"""U+AC00, the first precomposed Hangul syllable."""

_LAST_SYLLABLE: Final = "힣"
"""U+D7A3, the last one. The block between them holds all 11,172 syllables and nothing else."""


def display_form(text: str) -> str:
    """`text` tidied for display and storage: composed, trimmed, single-spaced.

    NFC, with surrounding whitespace removed and every inner run of whitespace (anything
    `str.isspace()` accepts, the ideographic space U+3000 included) turned into one ASCII
    space. Punctuation and letter case are kept: the user wrote them.
    """
    return " ".join(unicodedata.normalize("NFC", text).split())


def match_key(text: str) -> str:
    """The key under which two texts are the same word: equal keys, same word.

    The display form with every space and every punctuation character (any Unicode `P*`
    category) removed, then casefolded for Latin letters inside a Korean word. A readable
    string rather than a hash, so a stored key can be looked at.

    Composed once more at the end: removing a space from between two decomposed jamo
    (ᄀ ᅡ) puts them side by side, and only a second NFC makes them the 가 they spell, so
    the key stays idempotent. Casefolding can decompose a few rare Latin letters too.
    """
    kept = (
        char
        for char in display_form(text)
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )
    return unicodedata.normalize("NFC", "".join(kept).casefold())


def contains_hangul(text: str) -> bool:
    """Whether `text` holds at least one Hangul syllable once composed.

    Compatibility jamo and lone conjoining jamo do not count: neither is a syllable.
    """
    return any(
        _FIRST_SYLLABLE <= char <= _LAST_SYLLABLE for char in unicodedata.normalize("NFC", text)
    )
