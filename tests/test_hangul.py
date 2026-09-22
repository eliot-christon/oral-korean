"""Tests for Hangul normalisation: the display form, the match key and the Hangul check.

Framing-mode note: none of the production code below exists yet. These tests are written
from vocab-core T02's acceptance criteria and test contract, and they define the contract
the implementation must satisfy. Everything is imported from `oral_korean.korean.hangul`:
three pure functions, each taking one positional parameter named `text`.

- `display_form(text: str) -> str`: NFC, surrounding whitespace trimmed, every internal run
  of whitespace (anything `str.isspace()` accepts, U+3000 included) collapsed to one ASCII
  space. Nothing else changes: punctuation and letter case are kept.
- `match_key(text: str) -> str`: the display form with every space and every character of
  a Unicode punctuation category (`P*`) removed, then `str.casefold()`. Two texts are the
  same word exactly when their keys are equal. The key is a readable, composed string, not
  a hash, and it is pinned by value below.
- `contains_hangul(text: str) -> bool`: true when the NFC form holds at least one
  precomposed syllable, U+AC00 to U+D7A3. Compatibility jamo (the U+3131 block) and lone
  conjoining jamo do not count.

NFC only, never NFKC: compatibility jamo are never composed, so ㅅㅏㄱㅘ is not 사과. That
is the ticket's pinned decision (NFKC could not attach a final consonant anyway: 가ㄱ would
never become 각), and dropping one of its cases later is a weakened contract.

Two readings taken here, flagged in the hand-back report:

1. "Every operation is idempotent" cannot mean feeding a bool back into `contains_hangul`,
   so for the check it reads: the answer is the same for a text, its display form and its
   key, for every text in `MESSY_TEXTS`. Not for every text: the key composes jamo that
   only a space or a punctuation mark kept apart (ᄀ ᅡ has no syllable, its key is 가).
2. The key of a display form is the key of the raw text. That is what "the display form
   with ... removed" means, and it lets a caller keep only the display form and recompute
   the key from it later.

Symbols (category `S*`, such as `~` or `+`) are deliberately absent from every table: the
ticket does not decide whether they belong in the key.

How the inputs are built:

- every decomposed (NFD) input is made at runtime by `decomposed()`, which checks its
  code-point length, so a precomposed literal cannot stand in for one unnoticed;
- invisible characters (U+3000, the no-break space, tabs), and the punctuation that has an
  ASCII look-alike (curly quotes, the ellipsis), are written as escapes;
- the compatibility jamo literals (ㅅ, ㅏ, ㄱ, ㅘ) are U+3131-block letters, not the
  conjoining jamo NFD produces. Typed the wrong way, NFC would compose them, and the tests
  that pin them would fail rather than pass.

Pure calls throughout: no file, no patching.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

import pytest
from conftest import signature_shape

from oral_korean.korean.hangul import contains_hangul, display_form, match_key


def decomposed(text: str, length: int) -> str:
    """`text` in NFD, checked to hold exactly `length` code points.

    The length is the proof that the input really is decomposed: a precomposed string left
    here by mistake would be shorter, and every test using it would pass for the wrong
    reason.
    """
    result = unicodedata.normalize("NFD", text)
    assert len(result) == length, f"NFD {text!r} has {len(result)} code points, not {length}"
    return result


# Texts that need cleaning in every way the module cleans, and some that need none. The
# idempotency and consistency tests run over all of them.
MESSY_TEXTS = [
    pytest.param("  사과  ", id="surrounding-spaces"),
    pytest.param("사\u3000 과\t\n", id="mixed-whitespace"),
    pytest.param(decomposed("  감사   합니다.  ", 20), id="decomposed-sentence"),
    pytest.param("「사과」?", id="punctuation"),
    pytest.param("TV를  보다!", id="latin"),
    pytest.param("ㅅㅏㄱㅘ", id="compatibility-jamo"),
    pytest.param("가ㄱ", id="syllable-and-jamo"),
    pytest.param("?!", id="punctuation-only"),
    pytest.param("   ", id="spaces-only"),
    pytest.param("", id="empty"),
]

BLANK_TEXTS = [
    pytest.param("", id="empty"),
    pytest.param("   ", id="spaces"),
    pytest.param("\u3000", id="ideographic-space"),
    pytest.param(" \t\n\u00a0\u3000 ", id="mixed-whitespace"),
]


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "function",
    [display_form, match_key, contains_hangul],
    ids=["display_form", "match_key", "contains_hangul"],
)
def test_each_operation_takes_one_positional_text(function: Callable[..., object]) -> None:
    """T03 and vocab-sessions call these three by position; the name is part of the contract."""
    assert signature_shape(function) == (["text"], [])


# ---------------------------------------------------------------------------------
# Display form
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("사과", "사과", id="already-clean"),
        pytest.param("  사과  ", "사과", id="surrounding-spaces"),
        pytest.param("사   과", "사 과", id="inner-run-of-spaces"),
        pytest.param("사\u3000과", "사 과", id="inner-ideographic-space"),
        pytest.param("사과\t\n", "사과", id="trailing-tab-and-newline"),
        pytest.param("사과?", "사과?", id="punctuation-kept"),
        pytest.param("\u3000사과\u3000", "사과", id="surrounding-ideographic-spaces"),
        pytest.param("사 \t\u3000\n과", "사 과", id="inner-mixed-whitespace-run"),
        pytest.param("사\u00a0과", "사 과", id="inner-no-break-space"),
        pytest.param("  감사   합니다.  ", "감사 합니다.", id="sentence"),
        pytest.param("「사과」", "「사과」", id="brackets-kept"),
        pytest.param("TV를 보다", "TV를 보다", id="latin-case-kept"),
        pytest.param("ㅅㅏㄱㅘ", "ㅅㅏㄱㅘ", id="compatibility-jamo-not-composed"),
        pytest.param("가ㄱ", "가ㄱ", id="compatibility-final-not-attached"),
    ],
)
def test_display_form(text: str, expected: str) -> None:
    """The ticket's display table, plus the whitespace Unicode has besides the ASCII space.

    Only whitespace moves: punctuation, letter case and compatibility jamo come out as they
    went in. The last two cases are what NFKC would get wrong.
    """
    assert display_form(text) == expected


@pytest.mark.parametrize(
    ("text", "expected", "length"),
    [
        pytest.param(decomposed("사과", 4), "사과", 2, id="sagwa-4-to-2"),
        pytest.param(decomposed("각", 3), "각", 1, id="final-consonant-3-to-1"),
        pytest.param(decomposed("감사 합니다", 13), "감사 합니다", 6, id="phrase-13-to-6"),
        pytest.param("사" + decomposed("과", 2), "사과", 2, id="half-decomposed-3-to-2"),
    ],
)
def test_display_form_composes_decomposed_syllables(text: str, expected: str, length: int) -> None:
    """What a phone or macOS input method sends comes out as the syllables it looks like.

    The length is asserted as well as the text, so an expected value that was itself
    decomposed cannot make this pass.
    """
    result = display_form(text)

    assert result == expected
    assert len(result) == length


@pytest.mark.parametrize("text", BLANK_TEXTS)
def test_blank_text_has_an_empty_display_form(text: str) -> None:
    """Nothing but whitespace is nothing at all, not a lone space."""
    assert display_form(text) == ""


# ---------------------------------------------------------------------------------
# Match key
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("사과", "사과", id="already-a-key"),
        pytest.param("  사 과.  ", "사과", id="spaces-and-full-stop-removed"),
        pytest.param("사\u3000과", "사과", id="ideographic-space-removed"),
        pytest.param("「사과」", "사과", id="brackets-removed"),
        pytest.param(decomposed("사과", 4), "사과", id="decomposed-becomes-precomposed"),
        pytest.param("TV", "tv", id="latin-casefolded"),
        pytest.param("TV를  보다!", "tv를보다", id="phrase-with-latin"),
        pytest.param("ㅅㅏㄱㅘ", "ㅅㅏㄱㅘ", id="compatibility-jamo-kept-as-they-are"),
    ],
)
def test_match_key(text: str, expected: str) -> None:
    """The key is the display form without spaces or punctuation, casefolded.

    Pinned by value: a readable, composed string, so a key that merely compared equal (a
    hash, an NFD form) would still fail here.
    """
    assert match_key(text) == expected


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param(decomposed("사과", 4), id="decomposed"),
        pytest.param("사" + decomposed("과", 2), id="half-decomposed"),
        pytest.param("사 과", id="inner-space"),
        pytest.param(" 사과 ", id="surrounding-spaces"),
        pytest.param("사\u3000과", id="ideographic-space"),
        pytest.param("사과\t\n", id="trailing-tab-and-newline"),
        pytest.param("사과.", id="full-stop"),
        pytest.param("사과!", id="exclamation-mark"),
        pytest.param("사과?", id="question-mark"),
        pytest.param("「사과」", id="corner-brackets"),
        pytest.param("\u201c사과\u201d", id="curly-quotes"),
        pytest.param("(사과)", id="parentheses"),
        pytest.param("사과\u2026", id="ellipsis"),
        pytest.param("사과\u3002", id="ideographic-full-stop"),
        pytest.param("사-과", id="inner-hyphen"),
        pytest.param(decomposed(" 사 과? ", 8), id="everything-at-once"),
    ],
)
def test_every_spelling_of_a_word_shares_its_key(variant: str) -> None:
    """Decomposition, spacing and punctuation never make a different word.

    Every punctuation category is represented (open, close, initial and final quotes, dash,
    other), and removal is not limited to the ends of the text.
    """
    assert match_key(variant) == match_key("사과")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param("감사합니다", "감사 합니다", id="one-space"),
        pytest.param("감사합니다", "감 사 합 니 다", id="every-syllable-apart"),
        pytest.param(decomposed("감사합니다", 12), "감사 합니다", id="decomposed-and-spaced"),
    ],
)
def test_spacing_never_makes_a_different_word(left: str, right: str) -> None:
    """띄어쓰기 is ignored rather than checked: the ticket's rule, relied on by vocab-sessions."""
    assert match_key(left) == match_key(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param("사과", "사과요", id="extra-syllable"),
        pytest.param("사과", "샤과", id="one-vowel-off"),
        pytest.param("사과", "사가", id="second-syllable-off"),
        pytest.param("사과", "ㅅㅏㄱㅘ", id="compatibility-jamo-not-composed"),
        pytest.param("각", "가ㄱ", id="final-consonant-as-compatibility-jamo"),
        pytest.param("밥", "바", id="missing-final-consonant"),
        pytest.param("사과", "", id="empty-answer"),
        pytest.param("사과", "?", id="punctuation-only-answer"),
    ],
)
def test_different_words_have_different_keys(left: str, right: str) -> None:
    """Too lenient teaches a wrong spelling as right: one letter off is exactly the skill tested.

    An empty or punctuation-only answer must never match a word either.
    """
    assert match_key(left) != match_key(right)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(" ".join(decomposed("가", 2)), "가", id="space-between-initial-and-vowel"),
        pytest.param(".".join(decomposed("가", 2)), "가", id="full-stop-between-initial-and-vowel"),
        pytest.param("가 " + decomposed("각", 3)[-1], "각", id="space-before-final-consonant"),
        pytest.param("가." + decomposed("각", 3)[-1], "각", id="full-stop-before-final-consonant"),
        pytest.param(" ".join(decomposed("사과", 4)), "사과", id="every-jamo-apart"),
    ],
)
def test_jamo_kept_apart_by_what_the_key_removes_compose_into_their_syllable(
    text: str, expected: str
) -> None:
    """Removing a space or a punctuation mark can leave decomposed jamo side by side.

    The key composes them into the syllable they spell, so a separator never makes a
    different word, and the key stays its own key. Found by review: without a second NFC,
    the first key here was ᄀ + ᅡ, and keying it again gave 가.
    """
    key = match_key(text)

    assert key == expected
    assert match_key(key) == key


@pytest.mark.parametrize("text", BLANK_TEXTS)
def test_blank_text_has_an_empty_key(text: str) -> None:
    """The ticket's edge case: whitespace alone leaves nothing to compare."""
    assert match_key(text) == ""


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("?!", id="question-and-exclamation"),
        pytest.param("「」", id="empty-brackets"),
        pytest.param("...", id="full-stops"),
        pytest.param(" . ? ", id="spaced-out"),
        pytest.param("\u2026", id="ellipsis"),
    ],
)
def test_the_key_of_punctuation_alone_is_empty(text: str) -> None:
    """With every punctuation character removed, nothing is left."""
    assert match_key(text) == ""


# ---------------------------------------------------------------------------------
# Latin letters inside Korean
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param("TV", "tv", id="upper-and-lower"),
        pytest.param("TV", "Tv", id="mixed-case"),
        pytest.param("TV를 보다", "tv를 보다", id="inside-a-phrase"),
    ],
)
def test_latin_letters_inside_korean_match_whatever_their_case(left: str, right: str) -> None:
    """A loanword kept in Latin letters (TV) is one word, however it was capitalised."""
    assert match_key(left) == match_key(right)


def test_a_hangul_spelling_of_a_latin_word_is_a_different_word() -> None:
    """티비 is how TV is said, not how it is written: romanisation is excluded on purpose."""
    assert match_key("TV") != match_key("티비")


# ---------------------------------------------------------------------------------
# Contains Hangul
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("사과", True, id="word"),
        pytest.param("TV 보다", True, id="latin-and-hangul"),
        pytest.param(decomposed("사과", 4), True, id="decomposed"),
        pytest.param("가", True, id="first-syllable-u-ac00"),
        pytest.param("힣", True, id="last-syllable-u-d7a3"),
        pytest.param("apple", False, id="latin-only"),
        pytest.param("ㅅㅏ", False, id="compatibility-jamo-only"),
        pytest.param("", False, id="empty"),
        pytest.param("   ", False, id="spaces-only"),
        pytest.param("?!", False, id="punctuation-only"),
        pytest.param("\uabff", False, id="one-below-first-syllable"),
        pytest.param("\ud7a4", False, id="one-past-last-syllable"),
        pytest.param("\u1100", False, id="lone-conjoining-initial"),
        pytest.param("漢字", False, id="hanja"),
        pytest.param("123", False, id="digits"),
    ],
)
def test_contains_hangul(text: str, expected: bool) -> None:
    """Only a precomposed syllable counts, after NFC; the range is checked one past each end.

    `is` rather than `==`: the answer is a real bool, not a truthy match or count.
    """
    assert contains_hangul(text) is expected


# ---------------------------------------------------------------------------------
# Idempotency and consistency
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text", MESSY_TEXTS)
def test_display_form_is_idempotent(text: str) -> None:
    """Cleaning a clean text changes nothing, so a stored display form stays as stored."""
    once = display_form(text)

    assert display_form(once) == once


@pytest.mark.parametrize("text", MESSY_TEXTS)
def test_match_key_is_idempotent(text: str) -> None:
    """A key is its own key: comparing a stored key with a fresh one is always safe."""
    once = match_key(text)

    assert match_key(once) == once


@pytest.mark.parametrize("text", MESSY_TEXTS)
def test_contains_hangul_answers_the_same_for_a_text_and_its_cleaned_forms(text: str) -> None:
    """The check cannot be fed its own output, so its idempotency is this: cleaning one of
    these texts, for display or into a key, does not change whether it holds Hangul.

    The display form never changes it. The key can, for jamo a separator kept apart: see
    `test_jamo_kept_apart_by_what_the_key_removes_compose_into_their_syllable`.
    """
    expected = contains_hangul(text)

    assert contains_hangul(display_form(text)) is expected
    assert contains_hangul(match_key(text)) is expected


@pytest.mark.parametrize("text", MESSY_TEXTS)
def test_the_key_of_the_display_form_is_the_key_of_the_text(text: str) -> None:
    """The key is built on the display form, so keeping only the display form loses nothing."""
    assert match_key(display_form(text)) == match_key(text)
