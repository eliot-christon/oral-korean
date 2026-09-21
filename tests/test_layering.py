"""Import layering: every module in `korean/` and `exercises/` stays in its own layer.

The rule is the "Layering" invariant in `.claude/CRITERES_LITE.md`: `korean/` imports
nothing else in the project, `exercises/` imports `korean/` only, and neither reaches
`tts/`, `api/` or anything that talks to the outside world.

One parametrised test walks both packages, so a module added tomorrow (a future
`exercises/dates.py`) is checked the day it lands, without anyone editing this file. It
replaces two per-module purity tests that each named exactly one module, which left every
later module unguarded at precisely the moment the rule is likeliest to be broken.

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

KOREAN_PACKAGE = "oral_korean.korean"
EXERCISES_PACKAGE = "oral_korean.exercises"

FORBIDDEN_BY_PACKAGE: dict[str, tuple[str, ...]] = {
    # `korean/` imports nothing else in the project, and `exercises/` sits above it.
    KOREAN_PACKAGE: (*FORBIDDEN_IMPORTS, EXERCISES_PACKAGE),
    # `exercises/` may import `korean/`, so only the shared list applies to it.
    EXERCISES_PACKAGE: FORBIDDEN_IMPORTS,
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


# Each module paired with the forbidden set of the package it belongs to. Built when the
# file is collected, which is what lets a new module add a test case by existing.
MODULES: list[tuple[str, tuple[str, ...]]] = [
    (module_name, forbidden)
    for package_name, forbidden in FORBIDDEN_BY_PACKAGE.items()
    for module_name in discover_modules(package_name)
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

    The two package roots are pinned as well as the modules: dropping `__init__` from the
    walk would otherwise go unnoticed.
    """
    found = {module_name for module_name, _ in MODULES}

    assert {
        KOREAN_PACKAGE,
        EXERCISES_PACKAGE,
        "oral_korean.korean.numerals",
        "oral_korean.exercises.numbers",
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
    """The gap this file closes: `korean/` importing upward used to pass silently."""
    imported = {"oral_korean.exercises.numbers"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[KOREAN_PACKAGE]) == [
        "oral_korean.exercises.numbers"
    ]


def test_exercises_may_import_korean() -> None:
    """The other direction stays open: `exercises/` is built on `korean/`."""
    imported = {"oral_korean.korean.numerals"}

    assert forbidden_imports(imported, FORBIDDEN_BY_PACKAGE[EXERCISES_PACKAGE]) == []


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
        pytest.param("from .numerals import render_number", KOREAN_PACKAGE, id="sibling-korean"),
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
