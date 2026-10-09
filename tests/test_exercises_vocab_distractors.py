"""Tests for the multiple-choice distractors: offered because they resemble the right answer.

Written from vocab-harder-distractors' acceptance criteria before the implementation, through
the public API only: `build_question(word, direction, *, candidates, rng)` from
`oral_korean.exercises.vocab`. The ranking (same category first, a similarity score next, ties
broken through `rng`, three drawn among the closest six) is private, and its weights are the
implementation's: these tests pin outcomes, never numbers. Every fixture is chosen so that the
expected outcome holds under any weights that reward each signal the ticket names (shared final
syllables, syllable count, jamo similarity, a shared tag): a word kept out is never better than
a word let in on any signal, and is worse on at least one.

The category is read off the match key: a word whose key ends in 다 is a predicate.

Every word here has no memory in any direction, so every question is multiple choice, and each
has a single translation unique in its vocabulary, so an option on either side names its word.
The rest of the multiple-choice contract (the safety filter, distinct options, the fallback to
typing, a thin vocabulary) is pinned in `tests/test_exercises_vocab.py` and must still hold.

Pure calls throughout: no file, no patching. Random sources are always a seeded `random.Random`.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from oral_korean.exercises.vocab import AnswerMode, Direction, VocabQuestion, build_question
from oral_korean.exercises.vocab_words import VocabularyWord, same_memory
from oral_korean.srs.memory import Familiarity

ADDED: datetime = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)

SEEDS = range(50)
"""Fifty seeded draws: a candidate that is offered only sometimes cannot hide in them."""

DIRECTIONS = list(Direction)
DIRECTION_IDS = [direction.value for direction in DIRECTIONS]


def new_word(word_id: int, korean: str, translation: str, *tags: str) -> VocabularyWord:
    """A word never answered in any direction, so it is asked by multiple choice everywhere."""
    return VocabularyWord(
        id=word_id,
        korean=korean,
        translations=(translation,),
        tags=tuple(sorted(tags)),
        familiarity=Familiarity.NEW,
        added_at=ADDED,
        memories=same_memory(None),
    )


def numbered(
    entries: Sequence[tuple[str, str]], *tags: str, first_id: int
) -> tuple[VocabularyWord, ...]:
    """`entries` as words with consecutive ids from `first_id`, all carrying `tags`."""
    return tuple(
        new_word(first_id + offset, korean, translation, *tags)
        for offset, (korean, translation) in enumerate(entries)
    )


def question_for(
    target: VocabularyWord,
    direction: Direction,
    candidates: Sequence[VocabularyWord],
    seed_value: int,
) -> VocabQuestion:
    question = build_question(
        target, direction, candidates=candidates, rng=random.Random(seed_value)
    )
    assert question.mode is AnswerMode.CHOICE, question
    return question


def offered(
    target: VocabularyWord,
    direction: Direction,
    candidates: Sequence[VocabularyWord],
    seed_value: int,
) -> frozenset[str]:
    """The Korean of the words offered as distractors against `target` for one seed.

    Read off the options whichever side they are on: a Hangul option is its word's Korean, a
    translation option its word's one translation. The right option must appear exactly once.
    """
    question = question_for(target, direction, candidates, seed_value)
    assert question.correct_index is not None
    right = question.options[question.correct_index]
    assert question.options.count(right) == 1, question.options
    by_option = {word.korean: word.korean for word in candidates if word.id != target.id}
    by_option |= {word.translations[0]: word.korean for word in candidates if word.id != target.id}
    return frozenset(
        by_option[option]
        for index, option in enumerate(question.options)
        if index != question.correct_index
    )


def offered_across_seeds(
    target: VocabularyWord, direction: Direction, candidates: Sequence[VocabularyWord]
) -> list[frozenset[str]]:
    return [offered(target, direction, candidates, value) for value in SEEDS]


def koreans(words: Sequence[VocabularyWord]) -> frozenset[str]:
    return frozenset(word.korean for word in words)


# ---------------------------------------------------------------------------------
# The category ranks first
# ---------------------------------------------------------------------------------

GONGBUHADA = new_word(1, "공부하다", "to study", "study")
"""The ticket's verb. The nouns below share its tag, its first syllables or its length; the
verbs share nothing with it but the category."""

STUDY_NOUNS = numbered(
    [
        ("공부방", "study room"),
        ("공부벌레", "bookworm"),
        ("공부법", "study method"),
        ("공책", "notebook"),
        ("숙제", "homework"),
        ("학교", "school"),
        ("교실", "classroom"),
    ],
    "study",
    first_id=10,
)

PLAIN_VERBS = numbered(
    [
        ("가다", "to go"),
        ("오다", "to come"),
        ("먹다", "to eat"),
        ("자다", "to sleep"),
        ("보다", "to see"),
        ("읽다", "to read"),
        ("마시다", "to drink"),
    ],
    first_id=20,
)

STUDY_VOCABULARY = (GONGBUHADA, *STUDY_NOUNS, *PLAIN_VERBS)
"""The whole vocabulary, the target included, as the session hands it over."""


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize(
    ("target", "same_category"),
    [
        pytest.param(GONGBUHADA, koreans(PLAIN_VERBS), id="verb-among-verbs"),
        pytest.param(STUDY_NOUNS[0], koreans(STUDY_NOUNS[1:]), id="noun-among-nouns"),
    ],
)
def test_a_well_stocked_category_is_all_that_is_offered(
    target: VocabularyWord, same_category: frozenset[str], direction: Direction
) -> None:
    """With six or more eligible words in the target's category, no other word is ever
    offered, however much it looks like the target: 공부벌레 shares 공부하다's tag, length and
    first two syllables and is still never offered against it; 공부하다 shares 공부방's tag and
    first syllables and is never offered against it either."""
    for distractors in offered_across_seeds(target, direction, STUDY_VOCABULARY):
        assert len(distractors) == 3
        assert distractors <= same_category, distractors


MANNADA = new_word(1, "만나다", "to meet", "daily")

DAILY_NOUNS = numbered(
    [
        ("만두", "dumpling"),
        ("바나나", "banana"),
        ("나라", "country"),
        ("만화", "cartoon"),
        ("의자", "chair"),
        ("학교", "school"),
        ("가방", "bag"),
    ],
    "daily",
    first_id=10,
)
"""Nouns sharing 만나다's tag, and some its first or last syllables, or its length."""


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize(
    "verbs",
    [
        pytest.param((("먹다", "to eat"),), id="one-other-verb"),
        pytest.param((("먹다", "to eat"), ("자다", "to sleep")), id="two-other-verbs"),
        pytest.param((("먹 다.", "to eat"),), id="a-verb-spelled-loosely"),
    ],
)
def test_a_thin_category_is_offered_whole_and_the_rest_fill_in(
    verbs: tuple[tuple[str, str], ...], direction: Direction
) -> None:
    """Fewer than three other verbs: every one of them is offered, every time, and nouns make
    up the three. The category is read off the match key, so 먹 다. is a verb too."""
    other_verbs = numbered(verbs, first_id=30)
    candidates = (MANNADA, *DAILY_NOUNS, *other_verbs)

    for distractors in offered_across_seeds(MANNADA, direction, candidates):
        assert len(distractors) == 3
        assert koreans(other_verbs) <= distractors, distractors


# ---------------------------------------------------------------------------------
# Only the closest six are ever drawn
# ---------------------------------------------------------------------------------

UIJA = new_word(1, "의자", "chair")

CLOSE_TO_UIJA = numbered(
    [
        ("의사", "doctor"),
        ("모자", "hat"),
        ("과자", "snack"),
        ("피자", "pizza"),
        ("의미", "meaning"),
        ("액자", "picture frame"),
    ],
    first_id=10,
)
"""Two syllables like 의자, and one or two jamo away from it: 의사 differs by a single jamo."""

FAR_FROM_UIJA = numbered(
    [
        ("대한민국", "Korea"),
        ("텔레비전", "television"),
        ("아이스크림", "ice cream"),
    ],
    first_id=20,
)
"""Four syllables or more, a different final syllable, many jamo away, and no tag: never
better than a close word on any signal, worse on syllable count and jamo similarity."""


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize(
    "candidates",
    [
        pytest.param((*CLOSE_TO_UIJA, *FAR_FROM_UIJA), id="close-words-first"),
        pytest.param((*FAR_FROM_UIJA, *CLOSE_TO_UIJA), id="far-words-first"),
    ],
)
def test_only_the_six_closest_are_ever_offered_and_each_of_them_is(
    candidates: tuple[VocabularyWord, ...], direction: Direction
) -> None:
    """Exactly six words rank above the far ones, so those six are the pool: across the seeds
    every one of them is offered (의사 first among them, the ticket's case), and no far word
    ever is, wherever it sits in the vocabulary."""
    rounds = offered_across_seeds(UIJA, direction, candidates)
    every_offered = frozenset().union(*rounds)

    assert every_offered == koreans(CLOSE_TO_UIJA)
    assert every_offered.isdisjoint(koreans(FAR_FROM_UIJA))
    assert "의사" in every_offered


# ---------------------------------------------------------------------------------
# A shared tag, ties and the seed
# ---------------------------------------------------------------------------------

SAGWA = new_word(1, "사과", "apple", "fruit")

ENDING_IN_GWA = numbered(
    [
        ("효과", "effect"),
        ("결과", "result"),
        ("학과", "department"),
        ("성과", "achievement"),
        ("일과", "daily routine"),
    ],
    first_id=10,
)
"""Five words sharing 사과's length, its final syllable and some of its jamo."""

LOOKING_NOTHING_LIKE_SAGWA = (("머리", "head"), ("노루", "roe deer"))
"""Two syllables, like 사과, and not one jamo in common with it or a final syllable: equal to
each other on every signal but the tag."""


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize("tagged", [0, 1], ids=["meori-tagged", "noru-tagged"])
def test_a_shared_tag_lifts_a_word_into_the_pool_over_an_equal_one(
    tagged: int, direction: Direction
) -> None:
    """Seven candidates: the five ending in 과 rank first, and the sixth place goes to whichever
    of 머리 and 노루 shares 사과's tag. Swapping the tag swaps the outcome, so neither the
    vocabulary order nor the words themselves decide it."""
    pair = [
        new_word(30 + index, korean, translation, *(("fruit",) if index == tagged else ()))
        for index, (korean, translation) in enumerate(LOOKING_NOTHING_LIKE_SAGWA)
    ]
    lifted, left_out = pair[tagged], pair[1 - tagged]
    candidates = (*ENDING_IN_GWA, *pair)

    every_offered = frozenset().union(*offered_across_seeds(SAGWA, direction, candidates))

    assert lifted.korean in every_offered
    assert left_out.korean not in every_offered


EQUALLY_UNLIKE_SAGWA = numbered(
    [
        ("머리", "head"),
        ("노루", "roe deer"),
        ("우유", "milk"),
        ("모래", "sand"),
        ("두부", "tofu"),
        ("오리", "duck"),
        ("버터", "butter"),
        ("도로", "road"),
    ],
    first_id=40,
)
"""Eight words tied on every signal against 사과: two syllables, no jamo or final syllable in
common with it, no tag, no predicate. Only the random tie-break orders them."""


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_ties_are_broken_at_random_so_every_tied_word_is_reached(direction: Direction) -> None:
    """Eight tied words and a pool of six: a stable sort would keep the last two in
    vocabulary order out of every question."""
    every_offered = frozenset().union(
        *offered_across_seeds(SAGWA, direction, EQUALLY_UNLIKE_SAGWA)
    )

    assert every_offered == koreans(EQUALLY_UNLIKE_SAGWA)


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize(
    ("target", "candidates"),
    [
        pytest.param(GONGBUHADA, STUDY_VOCABULARY, id="ranked"),
        pytest.param(SAGWA, EQUALLY_UNLIKE_SAGWA, id="tied"),
    ],
)
def test_the_distractors_vary_with_the_seed(
    target: VocabularyWord, candidates: tuple[VocabularyWord, ...], direction: Direction
) -> None:
    """The same target does not always meet the same three neighbours."""
    assert len(set(offered_across_seeds(target, direction, candidates))) > 1


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
@pytest.mark.parametrize(
    ("target", "candidates"),
    [
        pytest.param(GONGBUHADA, STUDY_VOCABULARY, id="ranked"),
        pytest.param(SAGWA, EQUALLY_UNLIKE_SAGWA, id="tied"),
    ],
)
def test_the_same_seed_still_builds_the_same_question(
    target: VocabularyWord, candidates: tuple[VocabularyWord, ...], direction: Direction
) -> None:
    """The tie-break and the draw both go through the injected source, nothing else."""
    for value in (0, 7, 31):
        first = question_for(target, direction, candidates, value)
        second = question_for(target, direction, candidates, value)

        assert first == second


# ---------------------------------------------------------------------------------
# The safety filter still comes first
# ---------------------------------------------------------------------------------

UNSAFE_LOOKALIKES = (
    new_word(50, "공부 하다!", "to cram", "study"),
    new_word(51, "학습하다", "to study", "study"),
)
"""The two closest words to 공부하다 there could be: the same match key, and a shared
translation. Ranking must never bring either back."""


@pytest.mark.parametrize("direction", DIRECTIONS, ids=DIRECTION_IDS)
def test_the_closest_word_is_still_never_offered_if_it_could_be_right(
    direction: Direction,
) -> None:
    """Ranked first by any measure, refused all the same: the filter runs before the ranking.
    On the translation side 학습하다 would show as a second "to study", which `offered` refuses."""
    candidates = (*UNSAFE_LOOKALIKES, *PLAIN_VERBS)

    for distractors in offered_across_seeds(GONGBUHADA, direction, candidates):
        assert len(distractors) == 3
        assert distractors.isdisjoint(koreans(UNSAFE_LOOKALIKES))
