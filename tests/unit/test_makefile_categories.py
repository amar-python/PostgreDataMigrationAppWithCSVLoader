"""#276: a test category that collects no tests must fail, unless it is declared empty on purpose.

pytest exits 5 when it collects nothing. The Makefile's `run_category` used to turn that into success for every
category, so a renamed folder, a wrong path or a changed marker made `make test-<category>` pass without running a
test. Now only the categories named in `EMPTY_CATEGORIES` may be empty.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"


def declared_empty() -> list[str]:
    m = re.search(r"^EMPTY_CATEGORIES\s*:?=\s*(.*)$", MAKEFILE.read_text(encoding="utf-8"), re.M)
    return m.group(1).split() if m else []


def categories() -> list[str]:
    return re.findall(r"\$\(call run_category,(tests/[\w/]+)\)", MAKEFILE.read_text(encoding="utf-8"))


def run_category(folder: str, **variables: str) -> subprocess.CompletedProcess:
    """Run the Makefile's own run_category macro on `folder` through a throwaway makefile."""
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.mk"
        probe.write_text(f"include {MAKEFILE.as_posix()}\nprobe:\n\t$(call run_category,{folder})\n", encoding="utf-8")
        env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
        args = ["make", "-f", str(probe), "probe", *[f"{k}={v}" for k, v in variables.items()]]
        return subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


@pytest.mark.unit
@pytest.mark.regression
def test_the_categories_were_found():
    assert len(categories()) >= 5, "the parser found too few run_category calls in the Makefile"


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("folder", categories())
def test_a_category_holds_tests_or_is_declared_empty(folder):
    has_tests = any((ROOT / folder).rglob("test_*.py"))
    declared = folder in declared_empty()
    assert has_tests or declared, f"{folder} holds no tests and is not in EMPTY_CATEGORIES: `make` would now fail on it"
    assert not (has_tests and declared), f"{folder} now holds tests: take it out of EMPTY_CATEGORIES"


@pytest.mark.tooling
@pytest.mark.regression
def test_an_empty_category_that_is_not_declared_fails():
    with tempfile.TemporaryDirectory() as empty:
        result = run_category(Path(empty).as_posix(), EMPTY_CATEGORIES="")
    # make itself exits 2 when a recipe fails; "Error 5" is the recipe's own status (pytest's "nothing collected").
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Error 5" in result.stderr, result.stdout + result.stderr
    assert "No tests were collected" in result.stdout


@pytest.mark.tooling
@pytest.mark.regression
def test_an_empty_category_that_is_declared_passes_and_says_so():
    with tempfile.TemporaryDirectory() as empty:
        folder = Path(empty).as_posix()
        result = run_category(folder, EMPTY_CATEGORIES=folder)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "declared empty" in result.stdout
