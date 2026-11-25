"""#273: scripts/test_report.py must not report PASS for a run that executed nothing.

It treated only pytest's exit code 2 as "the run did not happen". A conftest that cannot be imported exits 4, nothing
collected exits 5, an internal error exits 3, and none of them put a test in the failed list, so the final block said
RESULT: PASS with 0 executed. For the browser job that meant a failed Playwright install would show a green check with
no test run. Only exit codes 0 (all passed) and 1 (some failed) mean tests ran, and a pass needs at least one executed.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def report(monkeypatch):
    spec = importlib.util.spec_from_file_location("test_report_script_codes", ROOT / "scripts" / "test_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main_with(report, monkeypatch, exit_code: int, passed=(), failed=(), errored=(), skipped=(), strict=False) -> int:
    monkeypatch.setattr(report, "_collect_all_ids", lambda paths=None: {f"t::{t}" for t in passed})
    monkeypatch.setattr(report, "_run", lambda markers, xml, paths=None: exit_code)
    monkeypatch.setattr(report, "_parse", lambda xml: (list(passed), list(failed), list(errored), list(skipped)))
    monkeypatch.setattr(sys, "argv", ["test_report.py", *(["--strict"] if strict else [])])
    return report.main()


@pytest.mark.parametrize("code", [2, 3, 4, 5])
def test_a_pytest_exit_code_that_means_nothing_ran_fails_the_report(report, monkeypatch, code):
    assert main_with(report, monkeypatch, code) == 1


@pytest.mark.parametrize("code", [2, 3, 4, 5])
def test_it_fails_even_when_some_results_exist(report, monkeypatch, code):
    assert main_with(report, monkeypatch, code, passed=["a"]) == 1


def test_a_clean_exit_with_nothing_executed_fails_the_report(report, monkeypatch):
    assert main_with(report, monkeypatch, 0) == 1


def test_all_passed_is_a_pass(report, monkeypatch):
    assert main_with(report, monkeypatch, 0, passed=["a", "b"]) == 0


def test_a_failure_is_a_fail(report, monkeypatch):
    assert main_with(report, monkeypatch, 1, passed=["a"], failed=[("b", "boom")]) == 1


def test_a_skip_is_a_fail_only_under_strict(report, monkeypatch):
    assert main_with(report, monkeypatch, 0, passed=["a"], skipped=[("b", "no db")]) == 0
    assert main_with(report, monkeypatch, 0, passed=["a"], skipped=[("b", "no db")], strict=True) == 1


def test_the_final_block_says_why_it_failed(report, monkeypatch, capsys):
    main_with(report, monkeypatch, 4)
    out = capsys.readouterr().out
    assert "pytest exit" in out and "4" in out
    assert "RESULT: FAIL" in out


def test_the_real_script_fails_when_a_conftest_cannot_be_imported(tmp_path):
    """The case that slipped through: no mocks, the real script and the real pytest on a folder whose conftest raises."""
    (tmp_path / "conftest.py").write_text("import a_module_that_does_not_exist_273\n", encoding="utf-8")
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/test_report.py", "--paths", str(tmp_path), "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 1, result.stdout[-600:]
    assert "RESULT: FAIL" in result.stdout
