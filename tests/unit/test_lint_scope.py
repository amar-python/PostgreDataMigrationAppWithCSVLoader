"""#322 (SE-01): scripts/lint.sh must lint every tracked Python file, not a list somebody keeps by hand.

The hand-kept PY_SRC list named 19 source files. The other 55 tracked Python files (all the routers, most of the
services, the Streamlit app, e2e/, the later migrations) were never checked by flake8 or bandit, so "lint clean" in
CI said nothing about the code that changes most. The same thing had already happened to the tests (#167).

Two kinds of check, both running the real script:
  * the scope the script reports (`--list-files`, `--list-security-files`) is what git tracks;
  * in a throwaway git repository, a new tracked file with a style error, or with a security finding, fails the lint,
    and a clean one passes. (The first draft of this file only compared lists, which cannot show the lists reach
    flake8 and bandit.)

Policy pinned here: flake8 checks every tracked .py file; bandit checks every tracked .py file except test code
(tests/ and e2e/), where its findings are about fixtures and asserts.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# `tooling` only, as for every test that runs the repo's shell scripts: the Windows job selects "unit or regression or
# security or snapshot", and on its runner `bash` is WSL's, which has no distribution installed. These run in the Linux
# integration job (everything except accessibility).
pytestmark = pytest.mark.tooling

ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / "scripts" / "lint.sh"
TEST_CODE = ("tests/", "e2e/")


def is_test_code(path: str) -> bool:
    """A tests/ folder at any depth (csv_loader/tests/) or e2e/, as in scripts/lint.sh."""
    return path.startswith(TEST_CODE) or "/tests/" in path


def short(paths, limit: int = 12) -> str:
    items = sorted(paths)
    return f"{len(items)} file(s): {items[:limit]}" + (" ..." if len(items) > limit else "")


def run_lint(*args: str, cwd: Path = ROOT, script: Path = LINT, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def tracked_python() -> set[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return {line for line in out.splitlines() if line}


def listed(flag: str) -> set[str]:
    result = run_lint(flag)
    assert result.returncode == 0, f"lint.sh {flag} exited {result.returncode}: {result.stderr[-400:]}"
    return {line for line in result.stdout.splitlines() if line}


def test_flake8_scope_is_every_tracked_python_file():
    tracked, linted, excluded = tracked_python(), listed("--list-files"), listed("--list-excluded")
    assert tracked - linted - excluded == set(), (
        f"tracked Python files that no lint run checks (and that are not in LINT_EXCLUDE): "
        f"{short(tracked - linted - excluded)}")
    assert linted - tracked == set(), f"lint.sh lists files git does not track: {short(linted - tracked)}"


def test_bandit_scope_is_every_tracked_python_file_except_test_code():
    tracked, secured, excluded = tracked_python(), listed("--list-security-files"), listed("--list-excluded")
    expected = {f for f in tracked if not is_test_code(f)} - excluded
    assert expected - secured == set(), f"source files bandit never scans: {short(expected - secured)}"
    assert secured - expected == set(), f"files bandit scans that it should not: {short(secured - expected)}"


def test_every_exclusion_is_a_tracked_file():
    assert listed("--list-excluded") - tracked_python() == set(), "LINT_EXCLUDE names a file git does not track"


@pytest.fixture
def scratch_repo(tmp_path: Path):
    """An empty git repository holding only a copy of scripts/lint.sh, so a test can add tracked files to it."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "scripts").mkdir()
    shutil.copy(LINT, tmp_path / "scripts" / "lint.sh")

    def add(rel: str, text: str) -> None:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)

    return tmp_path, add


def lint_in(repo: Path) -> subprocess.CompletedProcess:
    return run_lint(cwd=repo, script=repo / "scripts" / "lint.sh", timeout=120)


def test_a_clean_tracked_file_passes_the_lint(scratch_repo):
    repo, add = scratch_repo
    add("api/new_module.py", "def f():\n    return 1\n")
    result = lint_in(repo)
    assert result.returncode == 0, result.stdout[-600:] + result.stderr[-300:]


def test_a_new_tracked_file_with_a_style_error_fails_the_lint(scratch_repo):
    repo, add = scratch_repo
    add("api/new_module.py", "import os\n\n\ndef f():\n    return 1\n")  # F401: unused import
    result = lint_in(repo)
    assert result.returncode != 0, "a file nobody listed was not linted"
    assert "F401" in result.stdout + result.stderr, result.stdout[-600:]


def test_a_new_tracked_file_with_a_security_finding_fails_the_lint(scratch_repo):
    repo, add = scratch_repo
    add("api/fetch.py",
        "import urllib.request\n\n\ndef get(url):\n    return urllib.request.urlopen(url)\n")  # B310
    result = lint_in(repo)
    assert result.returncode != 0, "a source file nobody listed was not scanned by bandit"
    assert "B310" in result.stdout + result.stderr, result.stdout[-600:]


def test_test_code_is_style_checked_but_not_security_scanned(scratch_repo):
    repo, add = scratch_repo
    pattern = "import urllib.request\n\n\ndef test_x(url):\n    return urllib.request.urlopen(url)\n"
    add("tests/test_fetch.py", pattern)
    add("e2e/test_fetch.py", pattern)
    assert lint_in(repo).returncode == 0, "bandit should not scan tests/ or e2e/"
    add("tests/test_unused.py", "import os\n")  # but flake8 does
    result = lint_in(repo)
    assert result.returncode != 0 and "F401" in result.stdout + result.stderr


def test_test_code_in_a_package_folder_is_also_not_security_scanned(scratch_repo):
    """csv_loader/tests/ is test code like tests/: its fixtures build SQL and temp paths on purpose (bandit B608, B108)."""
    repo, add = scratch_repo
    add("csv_loader/tests/test_fetch.py",
        "import urllib.request\n\n\ndef test_x(url):\n    return urllib.request.urlopen(url)\n")  # B310 in a fixture
    assert lint_in(repo).returncode == 0, "bandit should not scan a tests/ folder inside a package"
    add("csv_loader/tests/test_unused.py", "import os\n")  # but flake8 does
    result = lint_in(repo)
    assert result.returncode != 0 and "F401" in result.stdout + result.stderr


def test_a_source_file_whose_folder_merely_contains_tests_in_its_name_is_still_scanned(scratch_repo):
    repo, add = scratch_repo
    add("api/contests/fetch.py", "import urllib.request\n\n\ndef get(url):\n    return urllib.request.urlopen(url)\n")
    result = lint_in(repo)
    assert result.returncode != 0 and "B310" in result.stdout + result.stderr, "only a folder named tests is test code"
