"""Import layering: every module in `korean/`, `srs/`, `exercises/` and `storage/` stays in
its own layer.

The rule is the "Layering" invariant in `.claude/CRITERES_LITE.md`: `korean/` and `srs/`
import nothing else in the project, `exercises/` imports `korean/` and `srs/` only,
`storage/` imports `korean/`, `srs/` and `exercises/` only, and none of the four reaches
`api/`, `tts/`, `config`, or anything else that talks to the outside world. `korean/`,
`srs/` and `exercises/` are pure in the stricter sense: none of the three may open a file
or a socket at all, `sqlite3` included. `storage/` (opened by vocab-core T04, the ticket
that gave the project its first persisted user data) is the one package allowed `sqlite3`,
and the one other package besides `api/` allowed to import `oral_korean.storage` - nothing
else may, so a database handle can only ever reach the rest of the project through the
layer built to compose everything, `api/`.

`srs/` is also the only package in the project that may import `fsrs`, as
`tts/melo_engine.py` is the only module that knows MeloTTS exists. Everything else handles
the project's own grade, memory-state and review-record values, never an `fsrs.Card`:
py-fsrs broke its API twice in 2025 (5.0 and 6.0), and containing it keeps the next upgrade a
one-package change.

One parametrised test walks the four packages, and a second walks every module under
`src/oral_korean/` looking for `fsrs`, so a module added tomorrow (a future
`exercises/dates.py`) is checked the day it lands, without anyone editing this file. They
replace per-module purity tests that each named exactly one module, which left every later
module unguarded at precisely the moment the rule is likeliest to be broken.

This is how the rule is enforced. A Claude Code hook was the other candidate and was
dropped: a pytest test runs in CI for every author, while a hook only ever saw Claude's
own edits.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from conftest import FORBIDDEN_IMPORTS, imported_module_names, imported_names_in_source

PROJECT_PACKAGE = "oral_korean"
KOREAN_PACKAGE = "oral_korean.korean"
EXERCISES_PACKAGE = "oral_korean.exercises"
SRS_PACKAGE = "oral_korean.srs"
STORAGE_PACKAGE = "oral_korean.storage"
API_PACKAGE = "oral_korean.api"

# `korean/`, `srs/` and `exercises/`: none of the three may open a file or a socket at all.
# `storage/` is deliberately not one of them - it is the layer that does open a file.
PURE_PACKAGES: tuple[str, ...] = (KOREAN_PACKAGE, EXERCISES_PACKAGE, SRS_PACKAGE)

# The FSRS library, which `srs/` alone may import.
FSRS = "fsrs"

# The database module, which `storage/` alone may import.
SQLITE3 = "sqlite3"


def rest_of_the_project(package_name: str) -> tuple[str, ...]:
    """Every top-level module and package of the project but `package_name`, by dotted name.

    Read from the project's directory rather than written out, because "imports nothing
    else in the project" is a rule about everything in it: a hand-kept list had already
    missed `config`, and would miss `storage/` (vocab-core T04) the day it lands.
    """
    project = importlib.import_module(PROJECT_PACKAGE)
    names = (
        f"{PROJECT_PACKAGE}.{module.name}" for module in pkgutil.iter_modules(project.__path__)
    )
    return tuple(name for name in names if name != package_name)


FORBIDDEN_BY_PACKAGE: dict[str, tuple[str, ...]] = {
    # `korean/` imports nothing else in the project: not the exercises built on it, not the
    # memory model, not the configuration.
    KOREAN_PACKAGE: (*FORBIDDEN_IMPORTS, *rest_of_the_project(KOREAN_PACKAGE)),
    # `exercises/` may import `korean/` and `srs/` (opened by vocab-core T03: a word's
    # familiarity and memory state are `srs/` values) and nothing else in the project -
    # `config` included, read from disk like every other sibling so a new one (`storage/`,
    # vocab-core T04) is forbidden the day it lands without anyone editing this file.
    EXERCISES_PACKAGE: (
        *FORBIDDEN_IMPORTS,
        *(
            name
            for name in rest_of_the_project(EXERCISES_PACKAGE)
            if name not in (KOREAN_PACKAGE, SRS_PACKAGE)
        ),
    ),
    # `srs/` imports nothing else in the project either. `fsrs` is not in the shared list:
    # it is `srs/`'s own dependency, and the check further down keeps it there.
    SRS_PACKAGE: (*FORBIDDEN_IMPORTS, *rest_of_the_project(SRS_PACKAGE)),
    # `storage/` (vocab-core T04) may import `korean/`, `srs/` and `exercises/` - the word
    # domain type it persists lives in `exercises/vocab_words.py` - and nothing else in the
    # project: `api/`, `tts/` and `config` stay closed, the same way they are to
    # `exercises/`. `sqlite3` is removed from the shared list: it is `storage/`'s own
    # dependency, the one package allowed to open a database file, and the check further
    # down keeps it there. `oral_korean.storage` is removed too, so the package does not
    # forbid itself.
    STORAGE_PACKAGE: (
        *(name for name in FORBIDDEN_IMPORTS if name not in (SQLITE3, STORAGE_PACKAGE)),
        *(
            name
            for name in rest_of_the_project(STORAGE_PACKAGE)
            if name not in (KOREAN_PACKAGE, SRS_PACKAGE, EXERCISES_PACKAGE)
        ),
    ),
}

# A throwaway package for proving the walk itself: a nested regular subpackage (which the
# walk must descend into) and a bare directory with no `__init__.py` (which it cannot see).
SYNTHETIC_PACKAGE = "layering_synthetic_pkg"
SYNTHETIC_FILES = (
    "__init__.py",
    "flat.py",
    "nested/__init__.py",
    "nested/deep.py",
    "bare/orphan.py",
)


def discover_modules(package_name: str) -> list[str]:
    """The package itself plus every module and subpackage beneath it, by dotted name.

    The package's own `__init__` is included on purpose: it is the natural home of a
    re-export, and `walk_packages` alone yields only what lies under it.
    """
    package = importlib.import_module(package_name)
    walked = pkgutil.walk_packages(package.__path__, prefix=f"{package_name}.")
    return [package_name, *(module.name for module in walked)]


def modules_on_disk(package_name: str) -> set[str]:
    """Every `.py` file beneath the package, by dotted name, found without the import system.

    The walk's independent oracle. `pkgutil` only descends into a directory that holds an
    `__init__.py`, yet Python still imports a module from a bare one, so such a module would
    slip past the layering check without a sound.
    """
    package = importlib.import_module(package_name)
    names: set[str] = set()
    for entry in package.__path__:
        root = Path(entry)
        for source in root.rglob("*.py"):
            parts = source.relative_to(root).with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            names.add(".".join((package_name, *parts)))
    return names


def is_within(module_name: str, package_name: str) -> bool:
    """True for the package itself and for anything beneath it, never for a mere namesake.

    `oral_korean.srs_tools` shares a prefix with `oral_korean.srs` without being part of it.
    """
    return module_name == package_name or module_name.startswith(f"{package_name}.")


# Each module paired with the forbidden set of the package it belongs to. Built when the
# file is collected, which is what lets a new module add a test case by existing.
MODULES: list[tuple[str, tuple[str, ...]]] = [
    (module_name, forbidden)
    for package_name, forbidden in FORBIDDEN_BY_PACKAGE.items()
    for module_name in discover_modules(package_name)
]

# Every module of the project, and those of them outside `srs/`: the ones that may never
# import `fsrs`. Built the same way, for the same reason.
PROJECT_MODULES: list[str] = discover_modules(PROJECT_PACKAGE)
OUTSIDE_SRS: list[str] = [name for name in PROJECT_MODULES if not is_within(name, SRS_PACKAGE)]

# Those outside `storage/`: the ones that may never import `sqlite3`. And those outside
# both `storage/` and `api/`: the ones that may never import `oral_korean.storage` itself,
# since `api/` is the only layer allowed to compose it with the rest of the project.
OUTSIDE_STORAGE: list[str] = [
    name for name in PROJECT_MODULES if not is_within(name, STORAGE_PACKAGE)
]
OUTSIDE_STORAGE_AND_API: list[str] = [
    name
    for name in PROJECT_MODULES
    if not is_within(name, STORAGE_PACKAGE) and not is_within(name, API_PACKAGE)
]


def forbidden_imports(imported: set[str], forbidden: tuple[str, ...]) -> list[str]:
    """The imported names that fall under a forbidden prefix, sorted for a stable message.

    The one filter behind both the per-module check and the tests that prove it bites, so
    what is proven is what runs.
    """
    return sorted(name for name in imported if name.startswith(forbidden))


# `name=` keeps the fixture's function name distinct from the parameter that receives it,
# which is what pylint's `redefined-outer-name` would otherwise flag in a same-file fixture.
@pytest.fixture(name="synthetic_package")
def make_synthetic_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """`SYNTHETIC_PACKAGE`, written under `tmp_path` and importable for this test only.

    Nothing is added under `src/`: the walk is proved on a package of its own.
    """
    for relative in SYNTHETIC_FILES:
        source = tmp_path / SYNTHETIC_PACKAGE / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("", encoding="utf-8")

    # monkeypatch: the package must be importable by name, and this undoes the path edit.
    monkeypatch.syspath_prepend(str(tmp_path))
    yield SYNTHETIC_PACKAGE

    # The walk imports subpackages, so drop them rather than leave modules whose directory
    # is about to disappear.
    for loaded in [name for name in sys.modules if name.partition(".")[0] == SYNTHETIC_PACKAGE]:
        del sys.modules[loaded]


def test_the_walk_finds_the_known_modules() -> None:
    """A broken or empty walk must not let the parametrised check below pass vacuously.

    The four package roots are pinned as well as the modules: dropping `__init__` from the
    walk would otherwise go unnoticed.
    """
    found = {module_name for module_name, _ in MODULES}

    assert {
        KOREAN_PACKAGE,
        EXERCISES_PACKAGE,
        SRS_PACKAGE,
        STORAGE_PACKAGE,
        "oral_korean.korean.numerals",
        "oral_korean.exercises.numbers",
        "oral_korean.exercises.vocab_words",
        "oral_korean.srs.memory",
        "oral_korean.storage.database",
        "oral_korean.storage.words",
    } <= found


@pytest.mark.parametrize("package_name", FORBIDDEN_BY_PACKAGE)
def test_the_walk_reaches_every_source_file_on_disk(package_name: str) -> None:
    """Every `.py` file under a package is one the layering test actually checks.

    A failure here is nearly always a new directory with no `__init__.py`: Python imports
    from it anyway, but the walk never opens it. Add the `__init__.py`.
    """
    checked = {module_name for module_name, _ in MODULES}

    assert modules_on_disk(package_name) - checked == set()


def test_the_disk_scan_reports_a_module_the_walk_misses(synthetic_package: str) -> None:
    """The guard above bites: the walk descends into a nested package, not a bare directory.

    `nested.deep` is reached by the walk, so it does recurse; `bare.orphan` is on disk and
    importable yet invisible to the walk, and the disk scan is what reports it.
    """
    walked = set(discover_modules(synthetic_package))

    assert f"{synthetic_package}.nested.deep" in walked
    assert modules_on_disk(synthetic_package) - walked == {f"{synthetic_package}.bare.orphan"}


@pytest.mark.parametrize(
    ("module_name", "forbidden"), MODULES, ids=[module_name for module_name, _ in MODULES]
)
def test_module_stays_within_its_layer(module_name: str, forbidden: tuple[str, ...]) -> None:
    """No module imports anything its layer forbids.

    Read statically from the source, so an import hidden inside a function is caught too.
    """
    module = importlib.import_module(module_name)

    assert forbidden_imports(imported_module_names(module), forbidden) == []


def test_forbidden_import_check_flags_a_violation() -> None:
    """The guard bites: a forbidden name is reported and an unrelated one is not."""
    imported = {"oral_korean.tts", "os"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]) == [
        "oral_korean.tts"
    ]


def test_korean_may_not_import_exercises() -> None:
    """The gap this file closed: `korean/` importing upward used to pass silently."""
    imported = {"oral_korean.exercises.numbers"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[KOREAN_PACKAGE]) == [
        "oral_korean.exercises.numbers"
    ]


def test_exercises_may_import_korean() -> None:
    """The other direction stays open: `exercises/` is built on `korean/`."""
    imported = {"oral_korean.korean.numerals"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]) == []


def test_korean_may_not_import_srs() -> None:
    """Language facts know nothing about how well a word is remembered."""
    imported = {"oral_korean.srs.memory"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[KOREAN_PACKAGE]) == [
        "oral_korean.srs.memory"
    ]


def test_exercises_may_import_srs() -> None:
    """Opened by vocab-core T03: a word's familiarity and memory state are `srs/` values."""
    imported = {"oral_korean.srs.memory"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]) == []


def test_exercises_may_not_import_config() -> None:
    """`korean/` and `srs/` only: a runtime setting is not a layer `exercises/` reaches for."""
    imported = {"oral_korean.config"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]) == [
        "oral_korean.config"
    ]


def test_storage_may_import_korean_srs_and_exercises() -> None:
    """Opened by vocab-core T04: `storage/` persists the `exercises/` word domain type,
    which itself carries `srs/` values, so all three stay open to it.
    """
    imported = {
        "oral_korean.korean.hangul",
        "oral_korean.srs.memory",
        "oral_korean.exercises.vocab_words",
    }

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]) == []


@pytest.mark.parametrize(
    "imported_name", ["oral_korean.api", "oral_korean.tts", "oral_korean.config"]
)
def test_storage_may_not_import_api_tts_or_config(imported_name: str) -> None:
    """`storage/` composes nothing itself: `api/` is the only layer that may reach into it."""
    assert forbidden_imports({imported_name}, FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]) == [
        imported_name
    ]


@pytest.mark.parametrize("package_name", PURE_PACKAGES, ids=["korean", "exercises", "srs"])
def test_no_pure_layer_may_import_storage(package_name: str) -> None:
    """`oral_korean.storage` joins the shared list (vocab-core T04): a pure module reaching
    for it could no longer be tested without a file on disk.
    """
    imported = {"oral_korean.storage"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[package_name]) == [
        "oral_korean.storage"
    ]


@pytest.mark.parametrize("package_name", [KOREAN_PACKAGE, SRS_PACKAGE], ids=["korean", "srs"])
def test_a_package_that_imports_nothing_else_forbids_every_other_part(package_name: str) -> None:
    """The rest of the project is read from disk, so pin that the reading found it.

    An empty `rest_of_the_project` would leave both packages guarded by the shared list
    alone, where `config` (and every later sibling) is missing. The package must not forbid
    itself either, or its own sibling imports would fail.
    """
    names = ("api", "config", "exercises", "korean", "srs", "storage", "tts")
    parts = {f"{PROJECT_PACKAGE}.{name}" for name in names}

    assert parts - {package_name} <= set(FORBIDDEN_BY_PACKAGE[package_name])
    assert package_name not in FORBIDDEN_BY_PACKAGE[package_name]


def test_exercises_forbids_every_part_of_the_project_but_korean_and_srs() -> None:
    """`rest_of_the_project` still found what `exercises/` may not import, `config` included.

    Not folded into the parametrised check above: `exercises/` is the one package that
    forbids the rest of the project *except* two named siblings, not every one of them.
    """
    names = ("api", "config", "storage", "tts")
    parts = {f"{PROJECT_PACKAGE}.{name}" for name in names}

    assert parts <= set(FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE])
    assert KOREAN_PACKAGE not in FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]
    assert SRS_PACKAGE not in FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]
    assert EXERCISES_PACKAGE not in FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]


def test_storage_forbids_every_part_of_the_project_but_korean_srs_and_exercises() -> None:
    """`storage/` (vocab-core T04) is the second package that forbids the rest of the
    project except a few named siblings, `sqlite3` included in what it does *not* forbid.
    """
    names = ("api", "config", "tts")
    parts = {f"{PROJECT_PACKAGE}.{name}" for name in names}

    assert parts <= set(FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE])
    assert KOREAN_PACKAGE not in FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]
    assert SRS_PACKAGE not in FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]
    assert EXERCISES_PACKAGE not in FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]
    assert STORAGE_PACKAGE not in FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]
    assert SQLITE3 not in FORBIDDEN_BY_PACKAGE[STORAGE_PACKAGE]


@pytest.mark.parametrize("package_name", PURE_PACKAGES, ids=["korean", "exercises", "srs"])
def test_no_pure_layer_may_import_sqlite3(package_name: str) -> None:
    """A database belongs to the storage layer (vocab-core T04), never to a pure one."""
    imported = imported_names_in_source("import sqlite3\nfrom sqlite3 import connect", package_name)

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[package_name]) == [
        "sqlite3",
        "sqlite3.connect",
    ]


# The tests below run real source through the extraction step rather than a ready-made set
# of names, because that step is where a spelling of an import can slip past the filter. The
# package is where the source lives, which is what a relative import resolves against.
@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        pytest.param("import oral_korean.tts", EXERCISES_PACKAGE, "oral_korean.tts", id="import"),
        pytest.param(
            "from oral_korean.tts import cache", EXERCISES_PACKAGE, "oral_korean.tts", id="from"
        ),
        pytest.param(
            "from oral_korean import tts", EXERCISES_PACKAGE, "oral_korean.tts", id="from-package"
        ),
        pytest.param(
            "from ..tts import cache", EXERCISES_PACKAGE, "oral_korean.tts", id="relative"
        ),
        pytest.param(
            "from .. import api", EXERCISES_PACKAGE, "oral_korean.api", id="relative-package"
        ),
        pytest.param(
            "def late():\n    from oral_korean import api",
            EXERCISES_PACKAGE,
            "oral_korean.api",
            id="inside-a-function",
        ),
        pytest.param(
            "from oral_korean import exercises",
            KOREAN_PACKAGE,
            "oral_korean.exercises",
            id="korean-from-package",
        ),
        pytest.param(
            "from ..exercises import numbers",
            KOREAN_PACKAGE,
            "oral_korean.exercises",
            id="korean-relative",
        ),
        pytest.param(
            "from ..srs import memory", KOREAN_PACKAGE, "oral_korean.srs", id="korean-srs"
        ),
        pytest.param(
            "from oral_korean.korean import numerals",
            SRS_PACKAGE,
            "oral_korean.korean",
            id="srs-korean",
        ),
        pytest.param(
            "from ..exercises import numbers",
            SRS_PACKAGE,
            "oral_korean.exercises",
            id="srs-relative",
        ),
        pytest.param(
            "from oral_korean import config", SRS_PACKAGE, "oral_korean.config", id="srs-config"
        ),
    ],
)
def test_every_spelling_of_a_forbidden_import_is_flagged(
    source: str, package: str, expected: str
) -> None:
    """`from oral_korean import tts` and `from ..tts import cache` mean what they say."""
    imported = imported_names_in_source(source, package)

    assert expected in forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[package])


@pytest.mark.parametrize(
    ("source", "package"),
    [
        pytest.param(
            "from oral_korean.korean.numerals import render_number",
            EXERCISES_PACKAGE,
            id="absolute",
        ),
        pytest.param(
            "from oral_korean.korean import numerals", EXERCISES_PACKAGE, id="from-package"
        ),
        pytest.param("from ..korean import numerals", EXERCISES_PACKAGE, id="relative"),
        pytest.param("from . import numbers", EXERCISES_PACKAGE, id="sibling-exercise"),
        pytest.param(
            "from oral_korean.srs.memory import Grade", EXERCISES_PACKAGE, id="exercises-srs"
        ),
        pytest.param("from .numerals import render_number", KOREAN_PACKAGE, id="sibling-korean"),
        pytest.param("from .memory import Grade", SRS_PACKAGE, id="sibling-srs"),
        pytest.param("from oral_korean.srs import memory", SRS_PACKAGE, id="srs-absolute-sibling"),
        pytest.param("from fsrs import Card, Scheduler", SRS_PACKAGE, id="srs-fsrs"),
        pytest.param("from datetime import UTC, datetime", SRS_PACKAGE, id="srs-stdlib"),
    ],
)
def test_the_allowed_spellings_are_not_flagged(source: str, package: str) -> None:
    """Resolving relative imports must not turn a legitimate one into a violation."""
    imported = imported_names_in_source(source, package)

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[package]) == []


def test_a_relative_import_is_resolved_against_the_modules_own_package(tmp_path: Path) -> None:
    """`imported_module_names` hands the module's package to the resolver, not its name.

    `from ..tts import cache` inside `oral_korean.exercises.mod` reaches `oral_korean.tts`;
    resolved against the module's own name it would read `oral_korean.exercises.tts` and
    pass. A stand-in module object avoids importing anything.
    """
    source = tmp_path / "mod.py"
    source.write_text("from ..tts import cache\n", encoding="utf-8")
    module = ModuleType("oral_korean.exercises.mod")
    module.__file__ = str(source)
    module.__package__ = EXERCISES_PACKAGE

    flagged = forbidden_imports(
        imported_module_names(module), FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]
    )

    assert "oral_korean.tts" in flagged


# ---------------------------------------------------------------------------------
# `fsrs` is imported by `srs/` and by nothing else
# ---------------------------------------------------------------------------------


def test_the_project_walk_reaches_every_source_file_on_disk() -> None:
    """The `fsrs` check below sees every `.py` file under `src/oral_korean/`.

    Same guard as the per-package one above, for the walk the `fsrs` check runs on.
    """
    assert modules_on_disk(PROJECT_PACKAGE) - set(PROJECT_MODULES) == set()


def test_the_project_walk_sees_both_sides_of_srs() -> None:
    """The `fsrs` check covers every other layer, and leaves `srs/` alone.

    Pinned by name so an empty walk, or a filter that dropped a whole layer, cannot let the
    parametrised check pass vacuously.
    """
    assert {
        PROJECT_PACKAGE,
        "oral_korean.config",
        "oral_korean.api.app",
        "oral_korean.tts.melo_engine",
        "oral_korean.korean.numerals",
        "oral_korean.exercises.numbers",
    } <= set(OUTSIDE_SRS)
    assert {SRS_PACKAGE, "oral_korean.srs.memory"} <= set(PROJECT_MODULES) - set(OUTSIDE_SRS)


@pytest.mark.parametrize("module_name", OUTSIDE_SRS, ids=OUTSIDE_SRS)
def test_no_module_outside_srs_imports_fsrs(module_name: str) -> None:
    """Only `srs/` knows FSRS exists; everything else handles the project's own values.

    Read statically, like the layering check, so a lazy import inside a function (the way
    `melo` is imported) is caught just the same.
    """
    module = importlib.import_module(module_name)

    assert forbidden_imports(imported_module_names(module), (FSRS,)) == []


def test_srs_is_where_fsrs_is_imported() -> None:
    """The name searched for above is the one `srs/` really imports.

    Otherwise the check could look for a name nobody uses and pass forever; this also
    records that `srs/` wraps the library rather than re-implementing FSRS.
    """
    importers = [
        module_name
        for module_name in discover_modules(SRS_PACKAGE)
        if forbidden_imports(imported_module_names(importlib.import_module(module_name)), (FSRS,))
    ]

    assert importers != []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("import fsrs", "fsrs", id="import"),
        pytest.param("from fsrs import Scheduler", "fsrs", id="from"),
        pytest.param("from fsrs.scheduler import Scheduler", "fsrs.scheduler", id="submodule"),
        pytest.param("def late():\n    import fsrs", "fsrs", id="inside-a-function"),
    ],
)
def test_every_spelling_of_an_fsrs_import_is_flagged(source: str, expected: str) -> None:
    """The guard bites on each way of writing the import, from outside `srs/`."""
    imported = imported_names_in_source(source, EXERCISES_PACKAGE)

    assert expected in forbidden_imports(imported, (FSRS,))


# ---------------------------------------------------------------------------------
# `sqlite3` is imported by `storage/` and by nothing else (vocab-core T04)
# ---------------------------------------------------------------------------------


def test_the_project_walk_sees_both_sides_of_storage() -> None:
    """The `sqlite3` check covers every other layer, `api/` included, and leaves `storage/`
    alone. Pinned by name for the same reason as the `fsrs` walk above.
    """
    assert {
        PROJECT_PACKAGE,
        "oral_korean.config",
        "oral_korean.api.app",
        "oral_korean.tts.melo_engine",
        "oral_korean.korean.numerals",
        "oral_korean.exercises.numbers",
        "oral_korean.srs.memory",
    } <= set(OUTSIDE_STORAGE)
    assert {STORAGE_PACKAGE, "oral_korean.storage.database"} <= (
        set(PROJECT_MODULES) - set(OUTSIDE_STORAGE)
    )


@pytest.mark.parametrize("module_name", OUTSIDE_STORAGE, ids=OUTSIDE_STORAGE)
def test_no_module_outside_storage_imports_sqlite3(module_name: str) -> None:
    """A database belongs to `storage/` alone; nothing else may open one directly.

    Read statically, like the layering check, so an import hidden inside a function is
    caught just the same.
    """
    module = importlib.import_module(module_name)

    assert forbidden_imports(imported_module_names(module), (SQLITE3,)) == []


def test_storage_is_where_sqlite3_is_imported() -> None:
    """The name searched for above is the one `storage/` really imports.

    Otherwise the check could look for a name nobody uses and pass forever; this also
    records that `storage/` is where the project's SQL lives.
    """
    importers = [
        module_name
        for module_name in discover_modules(STORAGE_PACKAGE)
        if forbidden_imports(
            imported_module_names(importlib.import_module(module_name)), (SQLITE3,)
        )
    ]

    assert importers != []


# ---------------------------------------------------------------------------------
# `oral_korean.storage` is imported by `storage/` and by `api/` only (vocab-core epic:
# "Nothing but `api/` imports `storage/`")
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name", OUTSIDE_STORAGE_AND_API, ids=OUTSIDE_STORAGE_AND_API
)
def test_no_module_outside_storage_and_api_imports_storage(module_name: str) -> None:
    """`api/` is the only layer that composes `storage/` with the rest of the project.

    `korean/`, `srs/` and `exercises/` are covered again here, project-wide rather than
    package-by-package, and so is `tts/`, which the per-package check never touches.
    """
    module = importlib.import_module(module_name)

    assert forbidden_imports(imported_module_names(module), (STORAGE_PACKAGE,)) == []
