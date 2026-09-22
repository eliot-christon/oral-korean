"""Words the user adds: a typed entry or a pasted list becomes validated word drafts.

The user adds words one at a time through a form, or by pasting a list with one word per line
(`사과 ; apple`), tags and a familiarity level applying to the whole batch. Either way the input
ends here, as frozen **word drafts** or as a refusal naming every problem in words the user can
act on. The **vocabulary word**, the one value storage returns and the quiz consumes, lives here
too: the vocabulary is the vocab exercise's data, and `exercises/` may never import the storage
that persists it, so the value sits below both.

Rules worth knowing before changing them:

- The Korean side is kept in T02's display form, and a draft exposes its match key as a
  property, so no caller recomputes it and no draft can carry a key that disagrees with its
  Korean.
- The Korean side must contain Hangul. That is what catches a line pasted the other way round
  (`apple ; 사과`), and when the translation side holds the Hangul the message says so.
- On a pasted line, the first `;` **or tab** separates the Korean from its translations, so two
  spreadsheet columns paste as they are; any later `;` separates translations.
- A pasted batch is **all or nothing**: every problem on every line is collected, numbered as
  the user sees the line in the text box (blank lines count), and any problem refuses the
  batch. Two lines for the same word are a problem too, and so is a line for a word already
  stored, when the caller passes the stored words in: this module has no database.
- The limits are guards against a paste gone wrong, not product rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from oral_korean.korean import hangul
from oral_korean.srs.memory import Familiarity, MemoryState

MAX_KOREAN_LENGTH: Final = 100
"""Characters in the Korean side's display form."""

MAX_TRANSLATION_LENGTH: Final = 100
"""Characters in one trimmed translation."""

MAX_TRANSLATIONS: Final = 10
"""Translations per word, counted after repeats are dropped."""

MAX_TAG_LENGTH: Final = 40
"""Characters in one normalised tag."""

MAX_PASTED_LINES: Final = 500
"""Non-blank lines in one paste."""

_BYTE_ORDER_MARK: Final = chr(0xFEFF)
_LINE_BREAK: Final = re.compile(r"\r\n|\r|\n")
_SIDE_SEPARATOR: Final = re.compile(r"[;\t]")
_TRANSLATION_SEPARATOR: Final = ";"


@dataclass(frozen=True)
class EntryProblem:
    """One reason an entry was refused.

    Attributes:
        line: the 1-based line of a paste, as the user sees it; `None` for a single entry, or
            for a problem with the whole batch (nothing to add, too many lines, a bad tag).
        message: what is wrong, in words the user can act on.
    """

    line: int | None
    message: str


class WordEntryError(ValueError):
    """An entry or a pasted batch was refused, for every reason listed in `problems`.

    One error type for every refusal here, subclassing `ValueError` as `NumeralError` and
    `InvalidRangeError` do, so the HTTP layer maps the whole family onto one response and can
    show every problem at once rather than one per attempt.
    """

    def __init__(self, problems: Sequence[EntryProblem]) -> None:
        self.problems: tuple[EntryProblem, ...] = tuple(problems)
        if not self.problems:
            raise ValueError("A WordEntryError needs at least one problem.")
        super().__init__("\n".join(_describe(problem) for problem in self.problems))


@dataclass(frozen=True)
class WordDraft:
    """A validated word, not yet stored.

    Attributes:
        korean: the Korean side, in T02's display form.
        translations: the accepted translations, in the order given; the first is shown first.
        tags: normalised and sorted.
        familiarity: how well the user said they know it, which seeds its memory when stored.
    """

    korean: str
    translations: tuple[str, ...]
    tags: tuple[str, ...]
    familiarity: Familiarity

    @property
    def match_key(self) -> str:
        """T02's match key for the Korean side: equal keys mean the same word."""
        return hangul.match_key(self.korean)


@dataclass(frozen=True)
class VocabularyWord:
    """A stored word: the one value storage returns and the quiz consumes.

    Attributes:
        id: storage's identifier.
        korean: the Korean side, in T02's display form.
        translations: the accepted translations, the first shown first.
        tags: normalised and sorted.
        familiarity: the level it was added with; it never changes afterwards.
        added_at: when it was added.
        memory: what FSRS knows about it, or `None` for a word never seeded nor answered.
    """

    id: int
    korean: str
    translations: tuple[str, ...]
    tags: tuple[str, ...]
    familiarity: Familiarity
    added_at: datetime
    memory: MemoryState | None


def parse_translations(text: str) -> tuple[str, ...]:
    """The translations in `text`, separated by `;`: trimmed, blanks and repeats dropped.

    Repeats are compared without case and the first spelling is kept, as is the order.

    Raises:
        WordEntryError: none remains, too many remain, or one is too long.
    """
    translations, messages = _check_translations(text)
    _refuse_if_any(messages)
    return translations


def normalise_tags(tags: Iterable[str]) -> tuple[str, ...]:
    """`tags` trimmed, single-spaced, casefolded, without blanks or repeats, and sorted.

    Raises:
        WordEntryError: a tag is too long.
    """
    normalised, messages = _check_tags(tags)
    _refuse_if_any(messages)
    return normalised


def make_draft(
    korean: str, translations: str, tags: Iterable[str], familiarity: Familiarity
) -> WordDraft:
    """The draft for one word typed in the add form.

    The Korean side, the translations and the tags are checked independently, and every
    problem is reported, so a form with two mistakes is not refused twice in a row.

    Raises:
        WordEntryError: any of the three is invalid.
    """
    display, korean_messages = _check_korean(korean, translations)
    parsed, translation_messages = _check_translations(translations)
    normalised, tag_messages = _check_tags(tags)
    _refuse_if_any([*korean_messages, *translation_messages, *tag_messages])
    return WordDraft(display, parsed, normalised, familiarity)


def parse_pasted_list(
    text: str, tags: Iterable[str], familiarity: Familiarity, *, stored: Iterable[str] = ()
) -> tuple[WordDraft, ...]:
    """The drafts for a pasted list, one word per non-blank line, in order.

    `tags` and `familiarity` apply to every word. A leading byte-order mark is ignored and any
    line-ending style is accepted. `stored` is the Korean of the words already in the
    vocabulary: a line for one of them is a problem on that line, as a repeat within the paste
    is, so a refusal lists every problem at once. The caller reads them; this module reads no
    database.

    Raises:
        WordEntryError: with every problem found, each on its line; nothing is returned in part.
    """
    normalised, numbered = _check_batch(text, tags)
    stored_by_key = {hangul.match_key(korean): korean for korean in stored}
    drafts: list[WordDraft] = []
    problems: list[EntryProblem] = []
    first_line_by_key: dict[str, int] = {}
    for number, line in numbered:
        korean, translations, messages = _parse_line(line)
        if korean is not None:
            messages.extend(_repeat_messages(korean, number, first_line_by_key, stored_by_key))
        problems.extend(EntryProblem(number, message) for message in messages)
        if korean is not None and not messages:
            drafts.append(WordDraft(korean, translations, normalised, familiarity))

    if problems:
        raise WordEntryError(problems)
    return tuple(drafts)


def _check_batch(text: str, tags: Iterable[str]) -> tuple[tuple[str, ...], list[tuple[int, str]]]:
    """A paste's normalised tags and its non-blank lines, or the refusal of the whole batch.

    Each line comes with its 1-based number as the user sees it: blank lines are dropped but
    still counted. Checked before any line is parsed, so a paste over the limit is one problem,
    not one per line.

    Raises:
        WordEntryError: a tag is too long, or there are no lines or too many.
    """
    normalised, tag_messages = _check_tags(tags)
    lines = _LINE_BREAK.split(text.removeprefix(_BYTE_ORDER_MARK))
    numbered = [(number, line) for number, line in enumerate(lines, start=1) if line.strip()]
    messages = [*tag_messages, *_line_count_messages(len(numbered))]
    if messages:
        raise WordEntryError([EntryProblem(None, message) for message in messages])
    return normalised, numbered


def _line_count_messages(count: int) -> list[str]:
    """What is wrong with a paste of `count` non-blank lines as a whole, checked first."""
    if count == 0:
        return ["Nothing to add: the list is empty."]
    if count > MAX_PASTED_LINES:
        return [f"A paste holds at most {MAX_PASTED_LINES} words, this one has {count}."]
    return []


def _parse_line(line: str) -> tuple[str | None, tuple[str, ...], list[str]]:
    """A pasted line's Korean side (`None` unless valid), its translations, and its problems.

    The first `;` or tab separates the two sides; a line with neither has only that problem.
    """
    separator = _SIDE_SEPARATOR.search(line)
    if separator is None:
        return None, (), ['No ";" or tab between the Korean and its translations.']
    korean, translations = line[: separator.start()], line[separator.end() :]
    display, korean_messages = _check_korean(korean, translations)
    parsed, translation_messages = _check_translations(translations)
    valid_korean = None if korean_messages else display
    return valid_korean, parsed, [*korean_messages, *translation_messages]


def _repeat_messages(
    korean: str, number: int, first_line_by_key: dict[str, int], stored_by_key: dict[str, str]
) -> list[str]:
    """Whether line `number`'s valid Korean is already stored, or on an earlier line.

    Records the line in `first_line_by_key` when it is the word's first. A stored word is
    named in its stored spelling, the one the user will find in their list.
    """
    key = hangul.match_key(korean)
    earlier = first_line_by_key.setdefault(key, number)
    if key in stored_by_key:
        return [f"{stored_by_key[key]} is already in the vocabulary."]
    if earlier != number:
        return [f"{korean} is already on line {earlier}."]
    return []


def _check_korean(korean: str, translations: str) -> tuple[str, list[str]]:
    """The Korean side's display form, and what is wrong with it.

    `translations` is only read to tell a swapped entry from a merely wrong one.
    """
    display = hangul.display_form(korean)
    if not display:
        return display, ["The Korean side is empty: it needs the word in Hangul."]
    if len(display) > MAX_KOREAN_LENGTH:
        return display, [
            f"The Korean side is at most {MAX_KOREAN_LENGTH} characters, "
            f"this one has {len(display)}."
        ]
    if not hangul.contains_hangul(display):
        if hangul.contains_hangul(translations):
            return display, [
                "The Korean side has no Hangul but the translation side has some: "
                "are the two swapped?"
            ]
        return display, ["The Korean side has no Hangul: write the word in Korean script."]
    return display, []


def _check_translations(text: str) -> tuple[tuple[str, ...], list[str]]:
    """The translations in `text`, and what is wrong with them."""
    kept: list[str] = []
    seen: set[str] = set()
    for part in text.split(_TRANSLATION_SEPARATOR):
        translation = part.strip()
        if translation and translation.casefold() not in seen:
            seen.add(translation.casefold())
            kept.append(translation)

    if not kept:
        return (), ["At least one translation is needed."]
    messages = [
        f"A translation is at most {MAX_TRANSLATION_LENGTH} characters, "
        f"one here has {len(translation)}."
        for translation in kept
        if len(translation) > MAX_TRANSLATION_LENGTH
    ]
    if len(kept) > MAX_TRANSLATIONS:
        messages.append(
            f"A word has at most {MAX_TRANSLATIONS} translations, this one has {len(kept)}."
        )
    return tuple(kept), messages


def _check_tags(tags: Iterable[str]) -> tuple[tuple[str, ...], list[str]]:
    """The normalised tags, and what is wrong with them.

    T02's display form does the trimming and the collapsing, and composes a tag typed in
    decomposed Hangul, so two tags that look the same are the same tag.
    """
    normalised = sorted({hangul.display_form(tag).casefold() for tag in tags} - {""})
    messages = [
        f'A tag is at most {MAX_TAG_LENGTH} characters, "{tag}" has {len(tag)}.'
        for tag in normalised
        if len(tag) > MAX_TAG_LENGTH
    ]
    return tuple(normalised), messages


def _refuse_if_any(messages: Sequence[str]) -> None:
    """Raise a `WordEntryError` for a single entry's problems, if it has any."""
    if messages:
        raise WordEntryError([EntryProblem(None, message) for message in messages])


def _describe(problem: EntryProblem) -> str:
    """One line of a refusal's text: the message, after its line number when it has one."""
    return problem.message if problem.line is None else f"Line {problem.line}: {problem.message}"
