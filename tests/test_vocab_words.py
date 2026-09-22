"""Tests for word drafts and pasted-list parsing: vocab-core T03's `vocab_words` module.

Framing-mode note: none of the production code below exists yet. These tests are written
from vocab-core T03's acceptance criteria and test contract, and they define the contract
the implementation must satisfy. Everything is imported from `oral_korean.exercises.vocab_words`:

- `WordEntryError(ValueError)`: `problems: tuple[EntryProblem, ...]`, never empty; `str(error)`
  holds every problem's message.
- `EntryProblem` (frozen): `line: int | None` (1-based, `None` for a single entry or a
  whole-batch problem), `message: str`.
- `WordDraft` (frozen): `korean`, `translations` (a tuple), `tags` (a tuple), `familiarity`
  (from `srs/`), plus a read-only `match_key` **property** (`hangul.match_key(korean)`, never
  a field, so a draft can never carry a key that disagrees with its Korean).
- `VocabularyWord` (frozen): `id`, `korean`, `translations`, `tags`, `familiarity`,
  `added_at`, `memory` (a `MemoryState | None` from `srs/`) - the value storage returns.
- `parse_translations(text) -> tuple[str, ...]`, `normalise_tags(tags) -> tuple[str, ...]`,
  `make_draft(korean, translations, tags, familiarity) -> WordDraft`,
  `parse_pasted_list(text, tags, familiarity) -> tuple[WordDraft, ...]`. All four positional
  parameters, no keyword-only ones, and all four raise `WordEntryError` on a refusal.
- `Final` limits: `MAX_KOREAN_LENGTH = 100`, `MAX_TRANSLATION_LENGTH = 100`,
  `MAX_TRANSLATIONS = 10`, `MAX_TAG_LENGTH = 40`, `MAX_PASTED_LINES = 500`.

Decisions taken here that the ticket leaves open, flagged in the hand-back report:

1. **Messages are pinned loosely**, by case-insensitive substrings, exactly as the ticket
   asks: never a full string. A swap hint is checked for the substring "swap"; a missing
   separator for `;`; a limit for its own number; a duplicate for the earlier line's number.
2. **Bulk fixtures never collide by match key.** `syllable(n)` builds a distinct precomposed
   Hangul syllable from `chr(0xAC00 + n)`, and `paste_of(count)` chains `count` of them into
   valid lines, as the ticket's practical notes ask - never a hand-typed block of 500 lines.
3. **The byte-order mark is `chr(0xFEFF)`**, never a literal invisible character typed into
   this file, and this file was grepped afterwards for one.
4. **Four thin `pytest.raises` wrappers** (`translations_refusal`, `tags_refusal`,
   `draft_refusal`, `refusal`) stand in for repeating the same three lines forty times: CI's
   duplicate-code check runs over `src/` and `tests/` together.
5. **The in-paste duplicate test keeps its earlier line valid.** The ticket leaves what
   happens when the earlier line was itself invalid unpinned, so no test claims it.
6. **"Assigning to any field raises"** is read as `dataclasses.FrozenInstanceError` for the
   four real `WordDraft` fields, and as either `FrozenInstanceError` or `AttributeError` for
   the `match_key` property (a frozen dataclass's generated `__setattr__` happens to block
   property assignment too, but that is not part of the ticket's pinned contract).
7. **Every "single entry" refusal is a `make_draft` call**, and every "batch" refusal a
   `parse_pasted_list` call: the ticket names both callers, so both are exercised for every
   rule that applies to each, not just one representative of "pure logic".

Pure calls throughout: no file, no patching, no clock.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from conftest import signature_shape

from oral_korean.exercises.vocab_words import (
    MAX_KOREAN_LENGTH,
    MAX_PASTED_LINES,
    MAX_TAG_LENGTH,
    MAX_TRANSLATION_LENGTH,
    MAX_TRANSLATIONS,
    EntryProblem,
    VocabularyWord,
    WordDraft,
    WordEntryError,
    make_draft,
    normalise_tags,
    parse_pasted_list,
    parse_translations,
)
from oral_korean.korean import hangul
from oral_korean.srs.memory import Familiarity

BOM = chr(0xFEFF)
"""A leading byte-order mark, never typed into this file as a literal invisible character."""


def only_problem(error: WordEntryError) -> EntryProblem:
    """The sole problem of a refusal expected to carry exactly one, not silently more."""
    assert len(error.problems) == 1, error.problems
    return error.problems[0]


def syllable(n: int) -> str:
    """A distinct precomposed Hangul syllable, so bulk fixtures never collide by match key."""
    return chr(0xAC00 + n)


def paste_of(count: int) -> str:
    """`count` distinct, valid pasted lines, one per Hangul syllable from `syllable`."""
    return "\n".join(f"{syllable(n)} ; w{n}" for n in range(count))


def translations_refusal(text: str) -> WordEntryError:
    """`parse_translations(text)`'s error, for an input expected to be refused."""
    with pytest.raises(WordEntryError) as excinfo:
        parse_translations(text)
    return excinfo.value


def tags_refusal(tags: list[str]) -> WordEntryError:
    """`normalise_tags(tags)`'s error, for an input expected to be refused."""
    with pytest.raises(WordEntryError) as excinfo:
        normalise_tags(tags)
    return excinfo.value


def draft_refusal(
    korean: str, translations: str, *, tags: list[str] | None = None
) -> WordEntryError:
    """`make_draft(korean, translations, ...)`'s error, for an entry expected to be refused."""
    with pytest.raises(WordEntryError) as excinfo:
        make_draft(korean, translations, tags if tags is not None else [], Familiarity.NEW)
    return excinfo.value


def refusal(
    text: str,
    *,
    tags: list[str] | None = None,
    familiarity: Familiarity = Familiarity.WELL,
    stored: tuple[str, ...] = (),
) -> WordEntryError:
    """`parse_pasted_list(text, ...)`'s error, for a paste expected to refuse the whole batch."""
    with pytest.raises(WordEntryError) as excinfo:
        parse_pasted_list(
            text, tags if tags is not None else ["food"], familiarity, stored=stored
        )
    return excinfo.value


# ---------------------------------------------------------------------------------
# Shape of the module
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("function", "positional", "keyword_only"),
    [
        pytest.param(parse_translations, ["text"], [], id="parse_translations"),
        pytest.param(normalise_tags, ["tags"], [], id="normalise_tags"),
        pytest.param(
            make_draft, ["korean", "translations", "tags", "familiarity"], [], id="make_draft"
        ),
        pytest.param(
            parse_pasted_list,
            ["text", "tags", "familiarity"],
            ["stored"],
            id="parse_pasted_list",
        ),
    ],
)
def test_public_signatures_keep_their_agreed_shape(
    function: Callable[..., object], positional: list[str], keyword_only: list[str]
) -> None:
    """The four functions T04 and T05 call by position; the names are part of the contract.

    `stored` (vocab-core T05) is keyword-only and optional: the words already in the
    vocabulary, which only the HTTP layer can read, so every earlier call stays valid.
    """
    assert signature_shape(function) == (positional, keyword_only)


def test_the_limits_are_the_tickets_own_numbers() -> None:
    """Named `Final` constants, asserted once by value: everything else builds from them."""
    assert MAX_KOREAN_LENGTH == 100
    assert MAX_TRANSLATION_LENGTH == 100
    assert MAX_TRANSLATIONS == 10
    assert MAX_TAG_LENGTH == 40
    assert MAX_PASTED_LINES == 500


def test_word_entry_error_is_a_value_error_carrying_every_problem() -> None:
    """One error type for every refusal, as `NumeralError` and `InvalidRangeError` are."""
    error = translations_refusal("")
    problems = error.problems

    assert isinstance(error, ValueError)
    assert problems != ()
    for problem in problems:
        assert isinstance(problem, EntryProblem)
        assert problem.message in str(error)


def test_entry_problem_is_a_frozen_value_with_line_and_message() -> None:
    """`line` is 1-based and `None` for a single entry or a whole-batch problem."""
    problem = EntryProblem(line=3, message="something is wrong")
    names = [field.name for field in dataclasses.fields(problem)]

    assert names == ["line", "message"]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(problem, name, None)


def test_a_word_draft_is_a_frozen_value_with_the_agreed_fields() -> None:
    """`match_key` is a read-only property, not a field: it can never disagree with `korean`."""
    draft = make_draft("사과", "apple", [], Familiarity.NEW)
    names = [field.name for field in dataclasses.fields(draft)]

    assert isinstance(draft, WordDraft)
    assert names == ["korean", "translations", "tags", "familiarity"]
    assert draft.match_key == hangul.match_key("사과")
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(draft, name, None)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        setattr(draft, "match_key", "다른")  # noqa: B010 - exercising the read-only property


def test_a_vocabulary_word_is_a_frozen_value_with_the_agreed_fields() -> None:
    """The one word value storage returns and the quiz consumes (T04, vocab-sessions)."""
    word = VocabularyWord(
        id=1,
        korean="사과",
        translations=("apple",),
        tags=(),
        familiarity=Familiarity.NEW,
        added_at=datetime(2026, 9, 21, tzinfo=UTC),
        memory=None,
    )
    names = [field.name for field in dataclasses.fields(word)]

    assert names == [
        "id",
        "korean",
        "translations",
        "tags",
        "familiarity",
        "added_at",
        "memory",
    ]
    for name in names:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(word, name, None)


# ---------------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("house; home", ("house", "home"), id="semicolon-space"),
        pytest.param("house;home", ("house", "home"), id="semicolon-no-space"),
        pytest.param(
            " house ;  home ; ", ("house", "home"), id="trailing-semicolon-adds-nothing"
        ),
        pytest.param("home; house", ("home", "house"), id="order-kept"),
        pytest.param("house; House", ("house",), id="case-insensitive-repeat-dropped"),
        pytest.param("ice cream", ("ice cream",), id="internal-spaces-kept"),
    ],
)
def test_parse_translations(text: str, expected: tuple[str, ...]) -> None:
    """Split on `;`, trim, drop blanks and case-insensitive repeats, keep the order."""
    assert parse_translations(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param(";", id="semicolon-only"),
        pytest.param(" ; ; ", id="semicolons-and-spaces"),
    ],
)
def test_parse_translations_refuses_when_nothing_remains(text: str) -> None:
    """At least one translation is needed; a lone separator is not one."""
    assert only_problem(translations_refusal(text)).line is None


def test_parse_translations_refuses_over_the_translation_limit() -> None:
    """Built from `MAX_TRANSLATIONS`, not the number typed out, so the limit stays the guard."""
    text = "; ".join(f"word{n}" for n in range(MAX_TRANSLATIONS + 1))

    assert str(MAX_TRANSLATIONS) in only_problem(translations_refusal(text)).message


def test_parse_translations_refuses_an_overlong_translation() -> None:
    """Built from `MAX_TRANSLATION_LENGTH`: one character past what a translation may hold."""
    text = "a" * (MAX_TRANSLATION_LENGTH + 1)

    assert str(MAX_TRANSLATION_LENGTH) in only_problem(translations_refusal(text)).message


# ---------------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------------


def test_normalise_tags_trims_collapses_casefolds_dedupes_and_sorts() -> None:
    """The ticket's own table: whitespace collapsed, case folded, blanks and repeats dropped."""
    assert normalise_tags([" TOPIK 1 ", "food", "Food", ""]) == ("food", "topik 1")


def test_normalise_tags_of_no_tags_is_empty() -> None:
    """A word may carry no tags at all."""
    assert not normalise_tags([])


def test_normalise_tags_refuses_an_overlong_tag() -> None:
    """Built from `MAX_TAG_LENGTH`: one character past what a tag may hold."""
    text = "a" * (MAX_TAG_LENGTH + 1)

    assert str(MAX_TAG_LENGTH) in only_problem(tags_refusal([text])).message


def test_a_tag_typed_in_decomposed_hangul_is_the_same_tag() -> None:
    """Added at implementation: tags go through T02's display form, so they are composed too.

    Otherwise a phone's 과일 and a desktop's 과일 would be two tags that look the same.
    """
    nfd_tag = unicodedata.normalize("NFD", "과일")
    assert len(nfd_tag) == 5  # sanity check: really decomposed

    assert normalise_tags([nfd_tag, "과일"]) == ("과일",)


# ---------------------------------------------------------------------------------
# Single draft
# ---------------------------------------------------------------------------------


def test_make_draft_builds_a_draft_with_the_display_form_and_match_key() -> None:
    """The plain case: a familiarity level, no tags, one translation."""
    draft = make_draft("사과", "apple", [], Familiarity.NEW)

    assert draft.korean == "사과"
    assert draft.translations == ("apple",)
    assert not draft.tags
    assert draft.familiarity is Familiarity.NEW
    assert draft.match_key == hangul.match_key("사과")


def test_make_draft_composes_a_decomposed_korean_side() -> None:
    """What a phone or macOS input method sends (NFD) comes out as the display form (T02)."""
    nfd_korean = unicodedata.normalize("NFD", "사과")
    assert len(nfd_korean) == 4  # sanity check: really decomposed, not the precomposed input

    draft = make_draft(nfd_korean, "apple", [], Familiarity.NEW)

    assert draft.korean == "사과"


def test_make_draft_normalises_its_tags() -> None:
    """The draft's tags are exactly what `normalise_tags` gives, not a re-implementation."""
    tags = [" TOPIK 1 ", "food", "Food", ""]

    draft = make_draft("사과", "apple", tags, Familiarity.NEW)

    assert draft.tags == normalise_tags(tags)


def test_make_draft_refuses_a_korean_side_with_no_hangul_and_hints_at_a_swap() -> None:
    """Catches a line pasted the other way round: the message must not leave the user guessing."""
    problem = only_problem(draft_refusal("apple", "사과"))
    message = problem.message.lower()

    assert problem.line is None
    assert "hangul" in message
    assert "swap" in message


def test_make_draft_hints_at_a_swap_only_when_the_translation_side_has_hangul() -> None:
    """Added at implementation: with no Hangul on either side, a swap would not help."""
    message = only_problem(draft_refusal("apple", "fruit")).message.lower()

    assert "hangul" in message
    assert "swap" not in message


def test_make_draft_refuses_a_blank_korean_side() -> None:
    """Whitespace only is nothing to match: refused like any other missing Korean side."""
    assert only_problem(draft_refusal("   ", "apple")).line is None


def test_make_draft_refuses_a_korean_side_over_the_length_limit() -> None:
    """Built from `MAX_KOREAN_LENGTH`: a paste artefact this long is a mistake, not a word."""
    too_long = syllable(0) * (MAX_KOREAN_LENGTH + 1)

    assert str(MAX_KOREAN_LENGTH) in only_problem(draft_refusal(too_long, "apple")).message


def test_the_korean_limit_counts_the_display_form_not_the_raw_input() -> None:
    """Settled for T03: a decomposed side at the limit holds twice as many code points."""
    nfd_korean = unicodedata.normalize("NFD", syllable(0) * MAX_KOREAN_LENGTH)
    assert len(nfd_korean) == 2 * MAX_KOREAN_LENGTH  # sanity check: each 가 is two jamo

    draft = make_draft(f"  {nfd_korean}  ", "apple", [], Familiarity.NEW)

    assert len(draft.korean) == MAX_KOREAN_LENGTH


def test_the_translation_and_tag_limits_count_the_trimmed_value() -> None:
    """Settled for T03: surrounding spaces are not part of what the limit guards."""
    translation = "a" * MAX_TRANSLATION_LENGTH
    tag = "a" * MAX_TAG_LENGTH

    draft = make_draft("사과", f"  {translation}  ", [f"  {tag}  "], Familiarity.NEW)

    assert draft.translations == (translation,)
    assert draft.tags == (tag,)


def test_make_draft_refuses_an_overlong_tag() -> None:
    """The four functions share one error type: a bad tag refuses the whole draft too."""
    overlong = "a" * (MAX_TAG_LENGTH + 1)

    error = draft_refusal("사과", "apple", tags=[overlong])

    assert str(MAX_TAG_LENGTH) in str(error)


def test_make_draft_reports_both_the_korean_and_translation_problems_independently() -> None:
    """" ; " gives two problems, per the ticket's own example: neither hides the other."""
    problems = draft_refusal("   ", "").problems

    assert len(problems) == 2
    assert all(problem.line is None for problem in problems)
    combined = " ".join(problem.message.lower() for problem in problems)
    assert "hangul" in combined
    assert "translation" in combined


def test_a_draft_is_frozen_end_to_end_when_built_through_make_draft() -> None:
    """Belt and braces on the constructed value, not only on a hand-built one."""
    draft = make_draft("사과", "apple", [], Familiarity.NEW)

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(draft, "korean", "다른")  # noqa: B010 - exercising frozen-dataclass enforcement


# ---------------------------------------------------------------------------------
# Pasted list
# ---------------------------------------------------------------------------------


def test_parse_pasted_list_returns_drafts_in_order_with_the_batch_tags_and_familiarity() -> None:
    """Two lines, two drafts, in order, both carrying the tags and familiarity for the batch."""
    text = "사과 ; apple\n배 ; pear; ship; belly"

    drafts = parse_pasted_list(text, ["food"], Familiarity.WELL)

    assert [draft.korean for draft in drafts] == ["사과", "배"]
    assert drafts[0].translations == ("apple",)
    assert drafts[1].translations == ("pear", "ship", "belly")
    assert all(draft.tags == ("food",) for draft in drafts)
    assert all(draft.familiarity is Familiarity.WELL for draft in drafts)


@pytest.mark.parametrize(
    "newline", [pytest.param("\r\n", id="crlf"), pytest.param("\r", id="cr")]
)
def test_parse_pasted_list_accepts_any_line_ending(newline: str) -> None:
    """Whatever line ending the user's editor or browser produced."""
    text = newline.join(["사과 ; apple", "배 ; pear; ship; belly"])

    drafts = parse_pasted_list(text, ["food"], Familiarity.WELL)

    assert [draft.korean for draft in drafts] == ["사과", "배"]
    assert drafts[1].translations == ("pear", "ship", "belly")


def test_blank_lines_count_towards_line_numbers_of_a_valid_paste() -> None:
    """A leading and an inner blank line change nothing about what gets parsed."""
    text = "\n사과 ; apple\n\n배 ; pear"

    drafts = parse_pasted_list(text, ["food"], Familiarity.WELL)

    assert [draft.korean for draft in drafts] == ["사과", "배"]


def test_parse_pasted_list_accepts_a_tab_as_the_first_separator() -> None:
    """A spreadsheet's two columns paste as is; a later `;` still splits the translations."""
    drafts = parse_pasted_list("사과\tapple; pomme", ["food"], Familiarity.WELL)

    assert drafts[0].korean == "사과"
    assert drafts[0].translations == ("apple", "pomme")


def test_a_leading_byte_order_mark_is_ignored() -> None:
    """A file saved with a BOM pastes as if it had none."""
    drafts = parse_pasted_list(f"{BOM}사과 ; apple", ["food"], Familiarity.WELL)

    assert len(drafts) == 1
    assert drafts[0].korean == "사과"


def test_parse_pasted_list_refuses_a_line_with_no_separator() -> None:
    """Neither `;` nor a tab: the message names what is missing, and only that."""
    problem = only_problem(refusal("사과 apple"))

    assert problem.line == 1
    assert ";" in problem.message


def test_parse_pasted_list_refuses_a_line_pasted_the_other_way_round() -> None:
    """The Korean side has no Hangul: the same swap hint as a single bad entry."""
    problem = only_problem(refusal("apple ; 사과"))

    assert problem.line == 1
    assert "hangul" in problem.message.lower()


def test_parse_pasted_list_refuses_a_line_with_no_korean() -> None:
    """A blank Korean side before the separator."""
    assert only_problem(refusal(" ; apple")).line == 1


def test_parse_pasted_list_refuses_a_line_with_no_translation() -> None:
    """A blank translations side after the separator."""
    assert only_problem(refusal("사과 ;")).line == 1


def test_parse_pasted_list_reports_both_problems_on_one_bad_line() -> None:
    """" ; " gives two problems on the same line, per the ticket's own example."""
    problems = refusal(" ; ").problems

    assert len(problems) == 2
    assert all(problem.line == 1 for problem in problems)


def test_parse_pasted_list_refuses_a_later_line_naming_an_earlier_word() -> None:
    """Two lines for the same word (T02's key), spelled with and without a space."""
    problem = only_problem(refusal("사과 ; apple\n사 과 ; apple"))

    assert problem.line == 2
    assert "1" in problem.message


def test_parse_pasted_list_refuses_a_line_for_a_word_already_stored() -> None:
    """vocab-core T05: a line whose word is stored (T02's key) is a problem on that line,
    naming the stored spelling, so the HTTP layer never has to find the line itself."""
    problem = only_problem(refusal("배 ; pear\n사 과 ; apple", stored=("사과",)))

    assert problem.line == 2
    assert "사과" in problem.message


def test_a_stored_duplicate_is_listed_with_every_other_problem() -> None:
    """All or nothing, every problem at once: an invalid line and a stored word, in order."""
    lines = ["apple ; pear", "배 ; pear", "사과 ; apple"]

    problems = refusal("\n".join(lines), stored=("사과",)).problems

    assert [problem.line for problem in problems] == [1, 3]


def test_a_stored_word_only_refuses_the_lines_that_repeat_it() -> None:
    """The stored words are what the caller hands over, and nothing else: others pass."""
    drafts = parse_pasted_list(
        "배 ; pear\n감 ; persimmon", ["food"], Familiarity.WELL, stored=("사과",)
    )

    assert [draft.korean for draft in drafts] == ["배", "감"]


def test_blank_lines_are_counted_in_a_reported_line_number() -> None:
    """Two leading blank lines before an invalid one: it is reported as line 4, not line 2."""
    problem = only_problem(refusal("\n사과 ; apple\n\napple ; pear"))

    assert problem.line == 4
    assert "hangul" in problem.message.lower()


def test_a_pasted_batch_collects_every_problem_by_line_in_order() -> None:
    """Three invalid lines among five, each with exactly one problem of its own."""
    words = [syllable(n) for n in range(4)]
    lines = [
        f"{words[0]} ; a",  # valid
        f"{words[1]} apple",  # missing separator
        f"{words[2]} ; c",  # valid
        "apple ; d",  # no Hangul
        f"{words[3]} ;",  # no translation
    ]

    problems = refusal("\n".join(lines)).problems

    assert [problem.line for problem in problems] == [2, 4, 5]


def test_a_batch_refusal_never_returns_partial_drafts() -> None:
    """Two of the three lines below are perfectly valid; the batch is refused whole regardless."""
    words = [syllable(n) for n in range(10, 12)]
    lines = [f"{words[0]} ; a", "apple ; b", f"{words[1]} ; c"]

    error = refusal("\n".join(lines))

    assert len(error.problems) == 1


def test_str_of_a_batch_refusal_holds_every_problems_message() -> None:
    """Three bad lines, three problems, and every one of their messages in `str(error)`."""
    words = [syllable(n) for n in range(20, 22)]
    lines = [f"{words[0]} apple", "apple ; b", f"{words[1]} ;"]

    error = refusal("\n".join(lines))
    text = str(error)

    assert len(error.problems) == 3
    for problem in error.problems:
        assert problem.message in text


@pytest.mark.parametrize(
    "text", [pytest.param("", id="empty"), pytest.param("\n\n  \n", id="blank-lines")]
)
def test_parse_pasted_list_refuses_an_empty_batch(text: str) -> None:
    """Nothing but blank lines is nothing to add: one batch problem, not zero drafts."""
    assert only_problem(refusal(text)).line is None


def test_parse_pasted_list_refuses_a_bad_batch_tag_as_one_problem_with_no_line() -> None:
    """A batch tag problem belongs to the whole paste, not to any one line."""
    overlong = "a" * (MAX_TAG_LENGTH + 1)

    problem = only_problem(refusal("사과 ; apple", tags=[overlong]))

    assert problem.line is None
    assert str(MAX_TAG_LENGTH) in problem.message


def test_parse_pasted_list_accepts_exactly_the_line_limit() -> None:
    """`MAX_PASTED_LINES` non-blank lines is still a normal paste."""
    drafts = parse_pasted_list(paste_of(MAX_PASTED_LINES), ["food"], Familiarity.WELL)

    assert len(drafts) == MAX_PASTED_LINES


def test_parse_pasted_list_refuses_one_line_over_the_limit() -> None:
    """Checked on non-blank lines before any line is parsed: one problem, no per-line ones."""
    problem = only_problem(refusal(paste_of(MAX_PASTED_LINES + 1)))

    assert problem.line is None
    assert str(MAX_PASTED_LINES) in problem.message
